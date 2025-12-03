"""
WebApp Analytics ETL Pipeline for Databricks

This module processes analytics data for various web applications (Wellness, Release Notes, VW Shop)
from Unity Catalog sources, applies transformations, and loads into target tables.

Key Features:
- Data anonymization (VIN, SSO ID)
- Event-based transformations per webapp
- Delta Lake persistence
- Modular and testable architecture
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol

import requests
from databricks import sql
from pyspark.sql import DataFrame, Row, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.functions import (
    col, concat, from_json, lead, lit, sha2, when
)
from pyspark.sql.types import (
    StringType, StructField, StructType, TimestampType
)
from pyspark.sql.window import Window


# ============================================================================
# CONFIGURATION
# ============================================================================

class WebAppId(str, Enum):
    """Supported WebApp identifiers."""
    WELLNESS = "carapp_wellness"
    RELEASE_NOTES = "carapp_orureleasenotes"
    VW_SHOP = "carapp_vwshop"


@dataclass(frozen=True)
class PipelineConfig:
    """Centralized configuration for the ETL pipeline."""

    # Unity Catalog paths
    source_table: str = "`ude_prod_euwe_daml`.`default`.`swabcd_vw_analytics_personalized_all_personalized`"
    target_schema: str = "`ude_prod_euwe_dataica-prod-dbuc`.`webapp`"

    # Databricks settings
    warehouse_name: str = "Serverless Starter Warehouse"
    secret_scope: str = "dataica-prod-local-secret-scope"

    # Processing settings
    lookback_days: int = 1

    @property
    def webapp_ids(self) -> List[str]:
        """Get list of all webapp IDs to process."""
        return [app.value for app in WebAppId]


@dataclass
class SecretKeys:
    """Secret key identifiers for Databricks secrets."""
    TENANT_ID = "ica-spn-tenant-id"
    CLIENT_ID = "ica-spn-client-id"
    CLIENT_SECRET = "ica-spn-client-secret"
    JDBC_PAT_TOKEN = "ica-jdbc-pat-token"
    VIN_SECRET = "ica-webapp-secret-vin"
    USER_SECRET = "ica-webapp-secret-ssoId"


# ============================================================================
# LOGGING SETUP
# ============================================================================

def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure structured logging for the pipeline."""
    logger = logging.getLogger(__name__)
    logger.setLevel(level)

    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


logger = setup_logging()


# ============================================================================
# PROTOCOLS & INTERFACES
# ============================================================================

class SecretManager(Protocol):
    """Protocol for secret management systems."""

    def get_secret(self, scope: str, key: str) -> str:
        """Retrieve secret value."""
        ...


class DataFrameWriter(Protocol):
    """Protocol for DataFrame persistence."""

    def write(self, df: DataFrame, table_name: str, mode: str = "append") -> None:
        """Write DataFrame to storage."""
        ...


# ============================================================================
# DATA ACCESS LAYER
# ============================================================================

class DatabricksSecretManager:
    """Manages retrieval of secrets from Databricks."""

    def __init__(self, dbutils: Any):
        self.dbutils = dbutils

    def get_secret(self, scope: str, key: str) -> str:
        """Retrieve a secret from Databricks secret scope."""
        try:
            return self.dbutils.secrets.get(scope=scope, key=key)
        except Exception as e:
            logger.error(f"Failed to retrieve secret '{key}' from scope '{scope}': {e}")
            raise


class WarehouseManager:
    """Manages Databricks SQL Warehouse connections."""

    def __init__(self, workspace_url: str, pat_token: str):
        self.workspace_url = workspace_url
        self.pat_token = pat_token
        self.api_url = f"https://{workspace_url}"

    def get_http_path(self, warehouse_name: str) -> str:
        """
        Retrieve HTTP path for specified SQL warehouse.

        Args:
            warehouse_name: Name of the warehouse

        Returns:
            HTTP path string for the warehouse

        Raises:
            ValueError: If warehouse not found
            requests.HTTPError: If API call fails
        """
        url = f"{self.api_url}/api/2.0/sql/warehouses"
        headers = {"Authorization": f"Bearer {self.pat_token}"}

        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            warehouses = response.json().get('warehouses', [])

            warehouse = next(
                (wh for wh in warehouses if wh['name'] == warehouse_name),
                None
            )

            if not warehouse:
                raise ValueError(f"Warehouse '{warehouse_name}' not found")

            return f"/sql/1.0/warehouses/{warehouse['id']}"

        except requests.RequestException as e:
            logger.error(f"Failed to fetch warehouse info: {e}")
            raise


class DataLoader:
    """Handles data loading from Unity Catalog."""

    def __init__(
        self,
        spark: SparkSession,
        warehouse_manager: WarehouseManager,
        config: PipelineConfig,
        jdbc_token: str
    ):
        self.spark = spark
        self.warehouse_manager = warehouse_manager
        self.config = config
        self.jdbc_token = jdbc_token

    def load_for_date(
        self,
        target_date: datetime,
        webapp_ids: Optional[List[str]] = None
    ) -> Dict[str, DataFrame]:
        """
        Load analytics data for specified date and webapps.

        Args:
            target_date: Date to load data for
            webapp_ids: Optional list of webapp IDs to filter (defaults to all)

        Returns:
            Dictionary mapping webapp_id to DataFrame
        """
        if webapp_ids is None:
            webapp_ids = self.config.webapp_ids

        date_str = int(target_date.strftime("%Y%m%d"))
        webapp_filter = "','".join(webapp_ids)

        query = f"""
            SELECT *
            FROM {self.config.source_table}
            WHERE webAppId IN ('{webapp_filter}')
            AND date = {date_str}
        """

        logger.info(f"Loading data for date {target_date.date()}, webapps: {webapp_ids}")

        try:
            http_path = self.warehouse_manager.get_http_path(self.config.warehouse_name)

            with sql.connect(
                server_hostname=self.spark.conf.get("spark.databricks.workspaceUrl"),
                http_path=http_path,
                access_token=self.jdbc_token
            ) as connection:
                cursor = connection.cursor()
                cursor.execute(query)
                rows = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description]
                cursor.close()

            df = self.spark.createDataFrame(rows, schema=columns)

            # Split by webapp
            result = {}
            for webapp_id in webapp_ids:
                webapp_df = df.filter(col("webAppId") == webapp_id)
                count = webapp_df.count()
                logger.info(f"Loaded {count} records for '{webapp_id}'")
                result[webapp_id] = webapp_df

            return result

        except Exception as e:
            logger.error(f"Failed to load data: {e}")
            raise


class DeltaWriter:
    """Handles writing DataFrames to Delta tables."""

    def __init__(self, target_schema: str):
        self.target_schema = target_schema

    def write(
        self,
        df: DataFrame,
        table_name: str,
        mode: str = "append",
        validate: bool = True
    ) -> None:
        """
        Write DataFrame to Delta table.

        Args:
            df: DataFrame to write
            table_name: Target table name (without schema)
            mode: Write mode (append, overwrite, etc.)
            validate: Whether to validate before writing
        """
        if validate and df.isEmpty():
            logger.warning(f"Skipping write to {table_name}: DataFrame is empty")
            return

        full_table_name = f"{self.target_schema}.`{table_name}`"
        record_count = df.count()

        logger.info(f"Writing {record_count} records to {full_table_name}")

        try:
            df.write.format("delta").mode(mode).saveAsTable(full_table_name)
            #df.show()
            logger.info(f"Successfully wrote to {full_table_name}")
        except Exception as e:
            logger.error(f"Failed to write to {full_table_name}: {e}")
            raise


# ============================================================================
# DATA ANONYMIZATION
# ============================================================================

class DataAnonymizer:
    """Handles PII anonymization using SHA-256 hashing."""

    ANONYMIZABLE_COLUMNS = ["vin", "ssoId"]

    def __init__(self, vin_secret: str, user_secret: str):
        self.secrets = {
            "vin": vin_secret,
            "ssoId": user_secret
        }

    def anonymize(self, df: DataFrame) -> DataFrame:
        """
        Anonymize sensitive columns in DataFrame.

        Args:
            df: Input DataFrame

        Returns:
            DataFrame with anonymized columns
        """
        result = df

        for column in self.ANONYMIZABLE_COLUMNS:
            if column in df.columns:
                secret = self.secrets.get(column)
                if secret:
                    result = result.withColumn(
                        column,
                        when(
                            col(column).isNotNull(),
                            sha2(concat(col(column), lit(secret)), 256)
                        ).otherwise(None)
                    )
                    logger.debug(f"Anonymized column: {column}")

        return result


# ============================================================================
# TRANSFORMERS
# ============================================================================

class WebAppTransformer(ABC):
    """Abstract base class for webapp-specific transformers."""

    def __init__(self, writer: DataFrameWriter):
        self.writer = writer

    @abstractmethod
    def transform_and_save(self, df: DataFrame) -> None:
        """
        Transform data and save to target tables.

        Args:
            df: Input DataFrame to transform
        """
        pass

    @property
    @abstractmethod
    def webapp_id(self) -> str:
        """Return the webapp ID this transformer handles."""
        pass


class WellnessTransformer(WebAppTransformer):
    """Transformer for Wellness webapp analytics."""

    @property
    def webapp_id(self) -> str:
        return WebAppId.WELLNESS.value

    def transform_and_save(self, df: DataFrame) -> None:
        """Transform wellness data into desktop, widget, and system events."""
        if df.isEmpty():
            logger.info(f"No data to transform for {self.webapp_id}")
            return

        logger.info(f"Transforming {self.webapp_id} data")

        # Prepare base DataFrame with timestamps
        df = self._prepare_base_dataframe(df)

        # Transform into different event types
        desktop_df = self._transform_desktop_events(df)
        widget_df = self._transform_widget_events(df)
        system_df = self._transform_system_events(df)

        # Save to tables
        self.writer.write(desktop_df, "desktop_wellness")
        self.writer.write(widget_df, "widget_wellness")
        self.writer.write(system_df, "system-events_wellness")

    def _prepare_base_dataframe(self, df: DataFrame) -> DataFrame:
        """Add timestamp and helper columns."""
        return (
            df
            .withColumn("ts_ms", col("timestamp").cast("long"))
            .withColumn(
                "eventtime",
                F.from_unixtime((col("ts_ms") / 1000)).cast("timestamp")
            )
            .withColumn(
                "value_from_name",
                F.regexp_extract(col("name"), r":\s*(.*)$", 1)
            )
        )

    def _transform_desktop_events(self, df: DataFrame) -> DataFrame:
        """Transform PageView events into desktop enter/leave events."""
        window = Window.partitionBy("vin", "ssoId", "guuid").orderBy("ts_ms")

        base = (
            df
            .filter((col("eventAction") == "PageView") & (col("eventCategory") == "Default"))
            .withColumn("view", F.regexp_replace(col("name"), r"^PageView - :\s*", ""))
            .withColumn("next_ts_ms", lead("ts_ms").over(window))
            .withColumn(
                "duration_ms",
                F.coalesce(col("next_ts_ms") - col("ts_ms"), lit(0)).cast("long")
            )
            .withColumn("screenarea", col("webAppId"))
        )

        enter_events = base.select(
            col("vin").alias("vehicleID"),
            "ssoId",
            "guuid",
            col("eventtime"),
            "screenarea",
            "view",
            lit("EnterView").alias("event"),
            col("duration_ms").alias("duration_in_ms"),
            col("appVersion").alias("softwareversion"),
            lit("webapp_wellness").alias("app_name")
        )

        leave_events = base.withColumn(
            "leave_eventtime",
            F.from_unixtime((F.coalesce(col("next_ts_ms"), col("ts_ms")) / 1000)).cast("timestamp")
        ).select(
            col("vin").alias("vehicleID"),
            "ssoId",
            "guuid",
            col("leave_eventtime").alias("eventtime"),
            "screenarea",
            "view",
            lit("LeaveView").alias("event"),
            lit(0).cast("long").alias("duration_in_ms"),
            col("appVersion").alias("softwareversion"),
            lit("webapp_wellness").alias("app_name")
        )

        return enter_events.unionByName(leave_events)

    def _transform_widget_events(self, df: DataFrame) -> DataFrame:
        """Transform user interaction events (scroll, buttons, tiles)."""
        # Scroll events
        scroll = (
            df
            .filter((col("eventAction") == "Scroll") & (col("eventCategory") == "Default"))
            .select(
                col("vin").alias("vehicleID"),
                "ssoId",
                "guuid",
                "eventtime",
                lit("Scrollbar").alias("widget"),
                lit("Scrollbar").alias("widgettype"),
                col("eventName").alias("action"),
                col("value_from_name").alias("value"),
                col("appVersion").alias("softwareversion"),
                lit("webapp_wellness").alias("app_name")
            )
        )

        # Cancel button events
        cancel = (
            df
            .filter(col("eventCategory") == "wellness.program.cancel.button")
            .select(
                col("vin").alias("vehicleID"),
                "ssoId",
                "guuid",
                "eventtime",
                col("eventCategory").alias("widget"),
                lit("Button").alias("widgettype"),
                col("eventAction").alias("action"),
                col("value_from_name").alias("value"),
                col("appVersion").alias("softwareversion"),
                lit("webapp_wellness").alias("app_name")
            )
        )

        # Button and tile events
        btn_tile = (
            df
            .filter(col("eventCategory").isin("tile", "Button"))
            .withColumn(
                "value_norm",
                when(F.lower(col("value_from_name")) == "true", lit("ON"))
                .when(F.lower(col("value_from_name")) == "false", lit("OFF"))
                .otherwise(col("value_from_name"))
            )
            .select(
                col("vin").alias("vehicleID"),
                "ssoId",
                "guuid",
                "eventtime",
                col("eventName").alias("widget"),
                col("eventCategory").alias("widgettype"),
                col("eventAction").alias("action"),
                col("value_norm").alias("value"),
                col("appVersion").alias("softwareversion"),
                lit("webapp_wellness").alias("app_name")
            )
        )

        return scroll.unionByName(cancel).unionByName(btn_tile)

    def _transform_system_events(self, df: DataFrame) -> DataFrame:
        """Transform system-level events (app start, settings, program start)."""
        # Initial settings (exploded key=value pairs)
        initial_settings = self._extract_initial_settings(df)

        # App start events
        app_start = (
            df
            .filter((col("eventCategory") == "system") & col("name").contains("application start"))
            .select(
                col("vin").alias("vehicleID"),
                "ssoId",
                "guuid",
                "eventtime",
                lit("AppStart").alias("event"),
                lit("").alias("parameter"),
                lit("").alias("value"),
                lit(None).cast("long").alias("duration_in_ms"),
                col("appVersion").alias("softwareversion"),
                lit("webapp_wellness").alias("app_name"),
                "ts_ms"
            )
        )

        # Program start events
        program_start = self._extract_program_start(df)

        # Other system events
        other_system = (
            df
            .filter(
                (col("eventCategory") == "system") &
                (~col("name").contains("Initial settings")) &
                (~col("name").contains("application start"))
            )
            .select(
                col("vin").alias("vehicleID"),
                "ssoId",
                "guuid",
                "eventtime",
                col("eventName").alias("event"),
                lit("").alias("parameter"),
                col("name").alias("value"),
                lit(-1).cast("long").alias("duration_in_ms"),
                col("appVersion").alias("softwareversion"),
                lit("webapp_wellness").alias("app_name"),
                "ts_ms"
            )
        )

        # Union all system events
        all_events = (
            initial_settings
            .unionByName(app_start)
            .unionByName(program_start)
            .unionByName(other_system)
        )

        # Calculate durations based on event sequence
        return self._calculate_durations(all_events)

    def _extract_initial_settings(self, df: DataFrame) -> DataFrame:
        """Extract and explode initial settings key=value pairs."""
        return (
            df
            .filter((col("eventCategory") == "system") & col("name").contains("Initial settings"))
            .withColumn("kv_str", F.regexp_extract(col("name"), r"Initial settings =>(.*)$", 1))
            .withColumn("kv_arr", F.split(col("kv_str"), r"\s*,\s*"))
            .withColumn("kv", F.explode_outer("kv_arr"))
            .withColumn("parameter", F.trim(F.split(col("kv"), "=", 2).getItem(0)))
            .withColumn("param_value", F.trim(F.split(col("kv"), "=", 2).getItem(1)))
            .select(
                col("vin").alias("vehicleID"),
                "ssoId",
                "guuid",
                "eventtime",
                lit("InitialSetting").alias("event"),
                col("parameter"),
                col("param_value").alias("value"),
                lit(None).cast("long").alias("duration_in_ms"),
                col("appVersion").alias("softwareversion"),
                lit("webapp_wellness").alias("app_name"),
                "ts_ms"
            )
        )

    def _extract_program_start(self, df: DataFrame) -> DataFrame:
        """Extract program start events from tile press events."""
        return (
            df
            .filter(
                (col("eventCategory") == "tile") &
                (col("eventAction") == "pressed") &
                (col("name").contains("pressed - wellness.program.tile."))
            )
            .withColumn("program_name", F.regexp_extract(col("eventName"), r"([^.]+)$", 1))
            .withColumn(
                "value_txt",
                concat(
                    lit("programStarted - Program_"),
                    col("program_name"),
                    lit(": Program "),
                    col("program_name"),
                    lit(" started")
                )
            )
            .select(
                col("vin").alias("vehicleID"),
                "ssoId",
                "guuid",
                "eventtime",
                concat(lit("Program_"), col("program_name")).alias("event"),
                lit("").alias("parameter"),
                col("value_txt").alias("value"),
                lit(None).cast("long").alias("duration_in_ms"),
                col("appVersion").alias("softwareversion"),
                lit("webapp_wellness").alias("app_name"),
                "ts_ms"
            )
        )

    def _calculate_durations(self, df: DataFrame) -> DataFrame:
        """Calculate event durations based on time differences."""
        window = Window.partitionBy("vehicleID", "ssoId", "guuid").orderBy("ts_ms")

        return (
            df
            .withColumn("prev_ts_ms", F.lag("ts_ms").over(window))
            .withColumn(
                "duration_in_ms",
                when(
                    (col("duration_in_ms") < 0) & col("prev_ts_ms").isNotNull(),
                    (col("ts_ms") - col("prev_ts_ms")).cast("long")
                ).otherwise(col("duration_in_ms"))
            )
            .drop("prev_ts_ms", "ts_ms")
            .orderBy("eventtime")
        )


class ReleaseNotesTransformer(WebAppTransformer):
    """Transformer for Release Notes webapp analytics."""

    @property
    def webapp_id(self) -> str:
        return WebAppId.RELEASE_NOTES.value

    def transform_and_save(self, df: DataFrame) -> None:
        """Transform release notes events into widget interactions."""
        if df.isEmpty():
            logger.info(f"No data to transform for {self.webapp_id}")
            return

        logger.info(f"Transforming {self.webapp_id} data")

        event_schema = self._get_event_schema()
        widget_schema = self._get_widget_schema()

        target_events = [
            "webapp_open_after_install",
            "time_open",
            "scroll_down",
            "download",
            "driver_distraction",
            "legal_info",
            "license_scrolled",
            "webapp_open_prior_install",
            "install_complete"
        ]

        widget_rows = []

        for row in df.collect():
            # Parse nested data column
            spark = df.sparkSession
            exploded_df = spark.createDataFrame(row['data'], event_schema)

            # Filter to relevant events and sort by timestamp
            filtered_df = (
                exploded_df
                .filter(col("eventName").isin(target_events))
                .orderBy("timestamp")
            )

            events = filtered_df.collect()

            # Create widget events with durations
            for i, event in enumerate(events):
                eventtime = datetime.fromtimestamp(int(event['timestamp']) / 1000)

                duration_ms = (
                    int(events[i + 1]['timestamp']) - int(event['timestamp'])
                    if i + 1 < len(events) else 0
                )

                widget_row = Row(
                    vehicleID=row['vin'],
                    ssoId=row['ssoId'],
                    guuid=row['guuid'],
                    eventtime=eventtime,
                    widget=event['eventName'],
                    widgettype=event['eventCategory'],
                    action=self._normalize_action(event['eventAction']),
                    value=event['eventValue'],
                    softwareversion=event['appVersion'],
                    app_name='carapp_orureleasenotes',
                    duration_in_ms=str(duration_ms)
                )
                widget_rows.append(widget_row)

        if widget_rows:
            spark = df.sparkSession
            widget_df = spark.createDataFrame(widget_rows, widget_schema)
            self.writer.write(widget_df, "widget_releasenotes")
            logger.info(f"Transformed {len(widget_rows)} release notes events")

    @staticmethod
    def _normalize_action(action: str) -> str:
        """Convert camelCase to snake_case if not already underscored."""
        if '_' in action:
            return action
        return re.sub(r'(?<!_)(?<=.)(?=[A-Z])', '_', action).lower()

    @staticmethod
    def _get_event_schema() -> StructType:
        """Define schema for nested event data."""
        return StructType([
            StructField("eventCategory", StringType(), True),
            StructField("eventAction", StringType(), True),
            StructField("eventValue", StringType(), True),
            StructField("eventName", StringType(), True),
            StructField("browserResolutionWidth", StringType(), True),
            StructField("browserResolutionHeight", StringType(), True),
            StructField("pageUrl", StringType(), True),
            StructField("entryPointType", StringType(), True),
            StructField("entryPointID", StringType(), True),
            StructField("applicationId", StringType(), True),
            StructField("appVersion", StringType(), True),
            StructField("shiftVersion", StringType(), True),
            StructField("timestamp", StringType(), True),
            StructField("name", StringType(), True),
            StructField("id", StringType(), True),
            StructField("uri", StringType(), True),
            StructField("webAppId", StringType(), True),
            StructField("event", StringType(), True)
        ])

    @staticmethod
    def _get_widget_schema() -> StructType:
        """Define schema for widget output data."""
        return StructType([
            StructField("vehicleID", StringType(), True),
            StructField("ssoId", StringType(), True),
            StructField("guuid", StringType(), True),
            StructField("eventtime", TimestampType(), True),
            StructField("widget", StringType(), True),
            StructField("widgettype", StringType(), True),
            StructField("action", StringType(), True),
            StructField("value", StringType(), False),
            StructField("softwareversion", StringType(), True),
            StructField("app_name", StringType(), True),
            StructField("duration_in_ms", StringType(), True)
        ])


class VWShopTransformer(WebAppTransformer):
    """Transformer for VW Shop webapp analytics."""

    @property
    def webapp_id(self) -> str:
        return WebAppId.VW_SHOP.value

    def transform_and_save(self, df: DataFrame) -> None:
        """Transform VW Shop events into desktop, widget, system, and unused tables."""
        if df.isEmpty():
            logger.info(f"No data to transform for {self.webapp_id}")
            return

        logger.info(f"Transforming {self.webapp_id} data")

        # Parse event JSON and classify
        df = self._parse_and_classify_events(df)

        # Transform and save each type
        self._save_desktop_events(df)
        self._save_widget_events(df)
        self._save_system_events(df)
        self._save_unused_events(df)

    def _parse_and_classify_events(self, df: DataFrame) -> DataFrame:
        """Parse nested event JSON and classify into table types."""
        event_schema = StructType([
            StructField("eventAction", StringType(), True),
            StructField("eventName", StringType(), True),
            StructField("eventValue", StringType(), True),
            StructField("referrer", StringType(), True),
            StructField("browserResolutionWidth", StringType(), True),
            StructField("browserResolutionHeight", StringType(), True),
            StructField("pageUrl", StringType(), True),
            StructField("entryPointType", StringType(), True),
            StructField("entryPointID", StringType(), True),
            StructField("applicationId", StringType(), True),
            StructField("appVersion", StringType(), True),
            StructField("shiftVersion", StringType(), True),
            StructField("timestamp", StringType(), True),
            StructField("eventCategory", StringType(), True),
            StructField("name", StringType(), True),
            StructField("id", StringType(), True),
            StructField("uri", StringType(), True),
            StructField("webAppId", StringType(), True),
            StructField("event", StringType(), True)
        ])

        df = df.withColumn("event_parsed", from_json(col("event"), event_schema))

        # Extract all relevant fields
        df = (
            df
            .withColumn("eventAction", col("event_parsed.eventAction"))
            .withColumn("eventCategory", col("event_parsed.eventCategory"))
            .withColumn("eventName", col("event_parsed.eventName"))
            .withColumn("eventValue", col("event_parsed.eventValue"))
            .withColumn("name", col("event_parsed.name"))
            .withColumn("pageUrl", col("event_parsed.pageUrl"))
            .withColumn("appVersion", col("event_parsed.appVersion"))
            .withColumn("entryPointType", col("event_parsed.entryPointType"))
            .withColumn("entryPointID", col("event_parsed.entryPointID"))
            .withColumn("referrer", col("event_parsed.referrer"))
            .withColumn("timestamp_ms", col("event_parsed.timestamp").cast("long"))
            .withColumn("eventtime", F.from_unixtime(col("timestamp_ms") / 1000).cast("timestamp"))
            .withColumn("systemevent", col("event_parsed.event"))
            .drop("event_parsed")
        )

        # Classify into table types
        df = df.withColumn(
            "table",
            when(
                col("eventAction") == "PageView", lit("desktop")
            ).when(
                col("eventName").isNotNull() & col("eventName").startswith("ICS"), lit("systemevent")
            ).when(
                col("eventName").isNotNull() & (~col("eventName").startswith("ICS")), lit("widget")
            ).otherwise(
                lit("notused")
            )
        )

        return df

    def _save_desktop_events(self, df: DataFrame) -> None:
        """Transform and save PageView desktop events."""
        window = Window.partitionBy("vin", "ssoId", "guuid").orderBy("timestamp_ms")

        base = (
            df
            .filter(col("table") == "desktop")
            .withColumn("next_ts_ms", lead("timestamp_ms").over(window))
            .withColumn(
                "duration_ms",
                F.coalesce(col("next_ts_ms") - col("timestamp_ms"), lit(0)).cast("long")
            )
        )

        enter_events = base.select(
            col("vin").alias("vehicleID"),
            "ssoId",
            "guuid",
            col("eventtime"),
            col("webAppId").alias("screenarea"),
            col("eventValue").alias("view"),
            lit("EnterView").alias("event"),
            col("duration_ms").alias("duration_in_ms"),
            col("appVersion").alias("softwareversion"),
            col("entryPointType"),
            col("entryPointID"),
            col("referrer"),
            col("eventCategory").alias("category")
        )

        leave_events = base.withColumn(
            "leave_eventtime",
            F.from_unixtime((F.coalesce(col("next_ts_ms"), col("timestamp_ms")) / 1000)).cast("timestamp")
        ).select(
            col("vin").alias("vehicleID"),
            "ssoId",
            "guuid",
            col("leave_eventtime").alias("eventtime"),
            col("webAppId").alias("screenarea"),
            col("eventValue").alias("view"),
            lit("LeaveView").alias("event"),
            lit(0).cast("long").alias("duration_in_ms"),
            col("appVersion").alias("softwareversion"),
            col("entryPointType"),
            col("entryPointID"),
            col("referrer"),
            col("eventCategory").alias("category")
        )

        desktop_df = enter_events.unionByName(leave_events)
        self.writer.write(desktop_df, "vwshop_desktop")

    def _save_widget_events(self, df: DataFrame) -> None:
        """Transform and save widget interaction events."""
        widget_df = df.filter(col("table") == "widget").select(
            col("vin").alias("vehicleID"),
            "ssoId",
            "guuid",
            col("eventtime"),
            col("eventName").alias("action"),
            col("name").alias("widget"),
            col("eventAction").alias("widgettype"),
            col("eventValue").alias("value"),
            col("appVersion").alias("softwareversion"),
            col("entryPointType"),
            col("entryPointID"),
            col("eventCategory").alias("category")
        )

        self.writer.write(widget_df, "vwshop_widget")

    def _save_system_events(self, df: DataFrame) -> None:
        """Transform and save system events (ICS*)."""
        systemevent_df = df.filter(col("table") == "systemevent").select(
            col("vin").alias("vehicleID"),
            "ssoId",
            "guuid",
            col("eventtime"),
            col("eventName").alias("parameter"),
            col("systemevent").alias("event"),
            col("eventValue").alias("value"),
            lit(None).cast("long").alias("duration_in_ms"),
            col("appVersion").alias("softwareversion"),
            col("entryPointType"),
            col("entryPointID"),
            col("eventCategory").alias("category")
        )

        self.writer.write(systemevent_df, "vwshop_systemevent")

    def _save_unused_events(self, df: DataFrame) -> None:
        """Save unclassified events for auditing."""
        notused_df = df.filter(col("table") == "notused").select(
            "guuid",
            "time",
            "webAppId",
            "eventId",
            col("eventCategory").alias("category"),
            "event",
            "consumer",
            "vin",
            "ssoId",
            col("date").cast("int")
        )

        self.writer.write(notused_df, "vwshop_not_used")


# ============================================================================
# ORCHESTRATION
# ============================================================================

class TransformerFactory:
    """Factory for creating webapp-specific transformers."""

    @staticmethod
    def create(webapp_id: str, writer: DataFrameWriter) -> WebAppTransformer:
        """
        Create appropriate transformer for webapp.

        Args:
            webapp_id: WebApp identifier
            writer: DataFrame writer instance

        Returns:
            Appropriate transformer instance

        Raises:
            ValueError: If webapp_id is not supported
        """
        transformers = {
            WebAppId.WELLNESS.value: WellnessTransformer,
            WebAppId.RELEASE_NOTES.value: ReleaseNotesTransformer,
            WebAppId.VW_SHOP.value: VWShopTransformer
        }

        transformer_class = transformers.get(webapp_id)
        if not transformer_class:
            raise ValueError(f"No transformer available for webapp: {webapp_id}")

        return transformer_class(writer)


class ETLPipeline:
    """Main orchestrator for the WebApp analytics ETL pipeline."""

    def __init__(
        self,
        spark: SparkSession,
        config: PipelineConfig
    ):
        self.spark = spark
        self.dbutils = dbutils
        self.config = config

        # Initialize components
        self.secret_manager = DatabricksSecretManager(dbutils)
        self._load_secrets()

        self.anonymizer = DataAnonymizer(
            self.secrets['vin'],
            self.secrets['user']
        )

        workspace_url = spark.conf.get("spark.databricks.workspaceUrl")
        self.warehouse_manager = WarehouseManager(
            workspace_url,
            self.secrets['jdbc_token']
        )

        self.loader = DataLoader(
            spark,
            self.warehouse_manager,
            config,
            self.secrets['jdbc_token']
        )

        self.writer = DeltaWriter(config.target_schema)

    def _load_secrets(self) -> None:
        """Load all required secrets from Databricks."""
        scope = self.config.secret_scope

        self.secrets = {
            'tenant_id': self.secret_manager.get_secret(scope, SecretKeys.TENANT_ID),
            'client_id': self.secret_manager.get_secret(scope, SecretKeys.CLIENT_ID),
            'client_secret': self.secret_manager.get_secret(scope, SecretKeys.CLIENT_SECRET),
            'jdbc_token': self.secret_manager.get_secret(scope, SecretKeys.JDBC_PAT_TOKEN),
            'vin': self.secret_manager.get_secret(scope, SecretKeys.VIN_SECRET),
            'user': self.secret_manager.get_secret(scope, SecretKeys.USER_SECRET)
        }

        logger.info("Successfully loaded all secrets")

    def run(self, target_date: Optional[datetime] = None) -> None:
        """
        Execute the complete ETL pipeline.

        Args:
            target_date: Optional date to process (defaults to yesterday)
        """
        if target_date is None:
            target_date = datetime.now() - timedelta(days=self.config.lookback_days)

        logger.info(f"Starting ETL pipeline for {target_date.date()}")

        try:
            # Load data
            webapp_dataframes = self.loader.load_for_date(target_date)

            # Anonymize PII
            for webapp_id, df in webapp_dataframes.items():
                webapp_dataframes[webapp_id] = self.anonymizer.anonymize(df)

            # Transform and save each webapp
            for webapp_id, df in webapp_dataframes.items():
                try:
                    transformer = TransformerFactory.create(webapp_id, self.writer)
                    transformer.transform_and_save(df)
                except Exception as e:
                    logger.error(f"Failed to transform {webapp_id}: {e}", exc_info=True)
                    # Continue with other webapps even if one fails

            logger.info("ETL pipeline completed successfully")

        except Exception as e:
            logger.error(f"ETL pipeline failed: {e}", exc_info=True)
            raise


# ============================================================================
# ENTRY POINT
# ============================================================================

def main(
    spark: SparkSession,
    config: Optional[PipelineConfig] = None,
    target_date: Optional[datetime] = None
) -> None:
    """
    Main entry point for the ETL pipeline.

    Args:
        spark: Active SparkSession
        dbutils: Databricks utilities
        config: Optional pipeline configuration (uses defaults if not provided)
        target_date: Optional specific date to process (defaults to yesterday)
    """
    if config is None:
        config = PipelineConfig()

    pipeline = ETLPipeline(spark, config)
    pipeline.run(target_date)


if __name__ == "__main__":
    spark_instance = SparkSession.builder.appName("WebappWellnessTransformData").getOrCreate()
    if not spark_instance:
        raise RuntimeError(
            "This script must run in a Databricks environment with spark available"
        )

    main(spark_instance)
