# Side-by-Side Code Comparison

This document shows specific code examples comparing the original implementation with the refactored version.

---

## Example 1: Data Anonymization

### ❌ Before: Global Dependencies & Hard-coded Logic

```python
def anonymize_columns(dataframe):
    columns = ["vin", "ssoId"]
    for c in columns:
        if c == "vin":
            secret = VIN_ANONYMIZATION_SECRET  # Global variable
        elif c == "ssoId":
            secret = USER_ANONYMIZATION_SECRET  # Global variable
        else:
            continue

        dataframe = dataframe.withColumn(
            c,
            when(col(c).isNotNull(), sha2(concat(col(c), lit(secret)), 256)).otherwise(None)
        )
    return dataframe
```

**Issues:**
- Depends on global variables
- Hard to test
- No type hints
- Magic number (256)
- Unclear purpose of each secret

### ✅ After: Clear, Testable, Type-safe

```python
class DataAnonymizer:
    """Handles PII anonymization using SHA-256 hashing."""

    ANONYMIZABLE_COLUMNS = ["vin", "ssoId"]

    def __init__(self, vin_secret: str, user_secret: str):
        """
        Initialize anonymizer with secrets.

        Args:
            vin_secret: Secret salt for VIN anonymization
            user_secret: Secret salt for user ID anonymization
        """
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

# Usage
anonymizer = DataAnonymizer(vin_secret="xyz", user_secret="abc")
anonymized_df = anonymizer.anonymize(input_df)

# Easy to test
def test_anonymization():
    mock_df = create_test_dataframe()
    anonymizer = DataAnonymizer("test_vin", "test_user")
    result = anonymizer.anonymize(mock_df)
    assert result.count() == mock_df.count()
```

**Improvements:**
- ✅ No global dependencies
- ✅ Full type hints
- ✅ Documented with docstrings
- ✅ Easily testable
- ✅ Logging for observability
- ✅ Class-level constants

---

## Example 2: Warehouse Connection

### ❌ Before: Mixed Concerns & Poor Error Handling

```python
def get_warehouse_http_path(warehouse_name):
    ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
    api_url = ctx.apiUrl().get()
    token = ctx.apiToken().get()

    warehouses_url = f"{api_url}/api/2.0/sql/warehouses"
    headers = {"Authorization": f"Bearer {token}"}

    response = requests.get(warehouses_url, headers=headers)  # No timeout!
    response.raise_for_status()

    warehouses = response.json().get('warehouses', [])

    warehouse = next((wh for wh in warehouses if wh['name'] == warehouse_name), None)

    if warehouse:
        return f"/sql/1.0/warehouses/{warehouse['id']}"
    else:
        raise ValueError(f"Warehouse '{warehouse_name}' não encontrado")
```

**Issues:**
- Depends on global `dbutils`
- No timeout on HTTP request (hangs forever if server unresponsive)
- No detailed error handling
- Mixed languages in error message
- Hard to test
- Gets token every time (inefficient)

### ✅ After: Clean, Robust, Testable

```python
class WarehouseManager:
    """Manages Databricks SQL Warehouse connections."""

    def __init__(self, workspace_url: str, pat_token: str):
        """
        Initialize warehouse manager.

        Args:
            workspace_url: Databricks workspace URL
            pat_token: Personal access token for authentication
        """
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

            http_path = f"/sql/1.0/warehouses/{warehouse['id']}"
            logger.info(f"Found warehouse '{warehouse_name}': {http_path}")
            return http_path

        except requests.Timeout:
            logger.error(f"Timeout connecting to Databricks API")
            raise
        except requests.HTTPError as e:
            logger.error(f"HTTP error fetching warehouse info: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            raise

# Usage
warehouse_mgr = WarehouseManager(workspace_url, token)
http_path = warehouse_mgr.get_http_path("My Warehouse")

# Easy to test
def test_warehouse_manager():
    with patch('requests.get') as mock_get:
        mock_get.return_value.json.return_value = {
            'warehouses': [{'name': 'Test', 'id': '123'}]
        }

        mgr = WarehouseManager("test.cloud.databricks.com", "fake_token")
        path = mgr.get_http_path("Test")

        assert path == "/sql/1.0/warehouses/123"
```

**Improvements:**
- ✅ No global dependencies (token passed in constructor)
- ✅ 30-second timeout prevents hanging
- ✅ Detailed error handling with logging
- ✅ Consistent English error messages
- ✅ Fully documented
- ✅ Easily testable with mocks
- ✅ Token reused efficiently

---

## Example 3: Data Loading

### ❌ Before: Monolithic Function

```python
def load_data(selected_date):
    query = f"""
        SELECT *
        FROM {BASE_UC_SOURCE_TABLE}
        WHERE webAppId IN ('{"','".join(WEBAPP_IDS)}')
        AND date = {int(selected_date.strftime("%Y%m%d"))}
    """
    with sql.connect(
            server_hostname=spark.conf.get("spark.databricks.workspaceUrl"),
            http_path=get_warehouse_http_path("Serverless Starter Warehouse"),
            access_token=jdbc_pat_token  # Global variable
    ) as connection:
        cursor = connection.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        cursor.close()

    df_d1 = spark.createDataFrame(rows, schema=columns)
    df_d1_anonymized = anonymize_columns(df_d1)

    # Split by webAppId
    final_df = {app: df_d1_anonymized.filter(col("webAppId") == app) for app in WEBAPP_IDS}
    return final_df
```

**Issues:**
- Uses global variables (BASE_UC_SOURCE_TABLE, WEBAPP_IDS, jdbc_pat_token, spark)
- Anonymization mixed with loading
- Hard-coded warehouse name
- No logging
- No error handling
- Hard to test

### ✅ After: Separation of Concerns

```python
class DataLoader:
    """Handles data loading from Unity Catalog."""

    def __init__(
        self,
        spark: SparkSession,
        warehouse_manager: WarehouseManager,
        config: PipelineConfig,
        jdbc_token: str
    ):
        """
        Initialize data loader.

        Args:
            spark: Active SparkSession
            warehouse_manager: Manager for warehouse connections
            config: Pipeline configuration
            jdbc_token: JDBC authentication token
        """
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

        Raises:
            ConnectionError: If database connection fails
            ValueError: If warehouse not found
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

        logger.info(
            f"Loading data for date {target_date.date()}, "
            f"webapps: {webapp_ids}"
        )

        try:
            http_path = self.warehouse_manager.get_http_path(
                self.config.warehouse_name
            )

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
            logger.error(f"Failed to load data: {e}", exc_info=True)
            raise

# Usage
loader = DataLoader(spark, warehouse_mgr, config, jdbc_token)
data = loader.load_for_date(datetime.now())

# Anonymization is separate
anonymizer = DataAnonymizer(vin_secret, user_secret)
for webapp_id, df in data.items():
    data[webapp_id] = anonymizer.anonymize(df)
```

**Improvements:**
- ✅ All dependencies injected (no globals)
- ✅ Single Responsibility (just loads data)
- ✅ Comprehensive logging
- ✅ Error handling with context
- ✅ Configurable via PipelineConfig
- ✅ Type hints and documentation
- ✅ Easily testable

---

## Example 4: Main Entry Point

### ❌ Before: Everything in Main

```python
def main(dbutils):
    # === Secrets Retrieval ===
    scope = f"dataica-prod-local-secret-scope"
    tenant_id = dbutils.secrets.get(scope=scope, key="ica-spn-tenant-id")
    client_id = dbutils.secrets.get(scope=scope, key="ica-spn-client-id")
    client_secret = dbutils.secrets.get(scope=scope, key="ica-spn-client-secret")
    jdbc_pat_token = dbutils.secrets.get(scope=scope, key="ica-jdbc-pat-token")
    VIN_ANONYMIZATION_SECRET = dbutils.secrets.get(scope=scope, key="ica-webapp-secret-vin")
    USER_ANONYMIZATION_SECRET = dbutils.secrets.get(scope=scope, key="ica-webapp-secret-ssoId")

    selected_date = datetime.now() - timedelta(days=1)
    print(f"Processing data for {selected_date.strftime('%Y-%m-%d')}")

    # === Load Data ===
    print(f"Loading data from SWABCD table...")
    df_by_webapp = load_data(selected_date)

    transformations = {
        CARAPP_WELLNESS_ID: transform_carapp_wellness,
        CARAPP_ORURELEASENOTES_ID: transform_carapp_orureleasenotes,
        CARAPP_VWSHOP_ID: transform_carapp_vwshop
    }

    for app, dframe in df_by_webapp.items():
        print(f"Data loaded for '{app}': {dframe.count()} records found.")
        if app in transformations:
            transformations[app](dframe)

if __name__ == "__main__":
    import builtins
    dbutils = getattr(builtins, "dbutils", None)
    main(dbutils)
```

**Issues:**
- Everything in one function (100+ lines)
- Manual secret management
- No error handling (one failure kills everything)
- Print statements instead of logging
- Hard to customize behavior
- Can't test without Databricks

### ✅ After: Clean Orchestration

```python
class ETLPipeline:
    """Main orchestrator for the WebApp analytics ETL pipeline."""

    def __init__(
        self,
        spark: SparkSession,
        dbutils: Any,
        config: PipelineConfig
    ):
        """
        Initialize ETL pipeline.

        Args:
            spark: Active SparkSession
            dbutils: Databricks utilities
            config: Pipeline configuration
        """
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
                    logger.error(
                        f"Failed to transform {webapp_id}: {e}",
                        exc_info=True
                    )
                    # Continue with other webapps even if one fails

            logger.info("ETL pipeline completed successfully")

        except Exception as e:
            logger.error(f"ETL pipeline failed: {e}", exc_info=True)
            raise


def main(
    spark: SparkSession,
    dbutils: Any,
    config: Optional[PipelineConfig] = None,
    target_date: Optional[datetime] = None
) -> None:
    """
    Main entry point for the ETL pipeline.

    Args:
        spark: Active SparkSession
        dbutils: Databricks utilities
        config: Optional pipeline configuration
        target_date: Optional specific date to process
    """
    if config is None:
        config = PipelineConfig()

    pipeline = ETLPipeline(spark, dbutils, config)
    pipeline.run(target_date)


if __name__ == "__main__":
    import builtins

    dbutils_instance = getattr(builtins, "dbutils", None)
    spark_instance = getattr(builtins, "spark", None)

    if not dbutils_instance or not spark_instance:
        raise RuntimeError(
            "This script must run in a Databricks environment"
        )

    main(spark_instance, dbutils_instance)
```

**Improvements:**
- ✅ Clear separation of concerns
- ✅ Graceful error handling (continues on failure)
- ✅ Structured logging
- ✅ Configurable behavior
- ✅ Components can be tested individually
- ✅ Better error messages
- ✅ Reusable pipeline class

---

## Example 5: Adding a New WebApp

### ❌ Before: Modify Multiple Places

```python
# Step 1: Add constant (top of file)
CARAPP_NEWAPP_ID = "carapp_newapp"

# Step 2: Add to list (top of file)
WEBAPP_IDS = [
    CARAPP_WELLNESS_ID,
    CARAPP_ORURELEASENOTES_ID,
    CARAPP_VWSHOP_ID,
    CARAPP_NEWAPP_ID  # <-- Add here
]

# Step 3: Write transformation function (middle of file)
def transform_carapp_newapp(df):
    # 200 lines of transformation code...
    df.write.format("delta").mode("append").saveAsTable("...")

# Step 4: Register in main (bottom of file)
transformations = {
    CARAPP_WELLNESS_ID: transform_carapp_wellness,
    CARAPP_ORURELEASENOTES_ID: transform_carapp_orureleasenotes,
    CARAPP_VWSHOP_ID: transform_carapp_vwshop,
    CARAPP_NEWAPP_ID: transform_carapp_newapp  # <-- Add here
}
```

**Issues:**
- Must modify 4 different places
- Easy to miss one location
- No compile-time checking
- Function name must match convention

### ✅ After: Add One Class

```python
# Step 1: Add to enum (optional, for type safety)
class WebAppId(str, Enum):
    WELLNESS = "carapp_wellness"
    RELEASE_NOTES = "carapp_orureleasenotes"
    VW_SHOP = "carapp_vwshop"
    NEW_APP = "carapp_newapp"  # <-- Just add here

# Step 2: Create transformer class
class NewAppTransformer(WebAppTransformer):
    """Transformer for New App analytics."""

    @property
    def webapp_id(self) -> str:
        return WebAppId.NEW_APP.value

    def transform_and_save(self, df: DataFrame) -> None:
        """Transform new app events."""
        if df.isEmpty():
            logger.info(f"No data to transform for {self.webapp_id}")
            return

        logger.info(f"Transforming {self.webapp_id} data")

        # Your transformation logic
        result_df = df.select(...)

        # Save using injected writer
        self.writer.write(result_df, "newapp_events")

# Step 3: Register in factory
class TransformerFactory:
    @staticmethod
    def create(webapp_id: str, writer: DataFrameWriter) -> WebAppTransformer:
        transformers = {
            WebAppId.WELLNESS.value: WellnessTransformer,
            WebAppId.RELEASE_NOTES.value: ReleaseNotesTransformer,
            WebAppId.VW_SHOP.value: VWShopTransformer,
            WebAppId.NEW_APP.value: NewAppTransformer,  # <-- Add here
        }

        transformer_class = transformers.get(webapp_id)
        if not transformer_class:
            raise ValueError(f"No transformer for: {webapp_id}")

        return transformer_class(writer)

# That's it! The pipeline automatically handles it.
```

**Improvements:**
- ✅ Only 2 places to modify (enum + factory)
- ✅ Type-safe with enum
- ✅ IDE autocomplete support
- ✅ Inherits error handling, logging, writer from base class
- ✅ Follows same pattern as existing transformers
- ✅ Can be tested independently

---

## Summary Table

| Aspect | Before | After |
|--------|--------|-------|
| **Type Safety** | No type hints | Full type hints |
| **Logging** | `print()` statements | Structured `logging` with levels |
| **Error Handling** | None (crashes on error) | Try/except with graceful degradation |
| **Testability** | Impossible without Databricks | Fully testable with mocks |
| **Configuration** | Hard-coded strings everywhere | Centralized `PipelineConfig` |
| **Documentation** | None | Comprehensive docstrings |
| **Dependencies** | Global state | Dependency injection |
| **Code Organization** | Flat procedural | Layered OOP architecture |
| **Extensibility** | Modify multiple places | Add one class |
| **Observability** | Basic print output | Structured logs + metrics ready |

---

## Conclusion

The refactored version demonstrates that **good software engineering practices apply even in data engineering scripts**. The additional structure provides:

- **Safety**: Type hints catch errors before runtime
- **Reliability**: Error handling prevents cascading failures
- **Maintainability**: Clear structure makes changes easier
- **Testability**: Dependency injection enables unit testing
- **Observability**: Structured logging enables monitoring

This transformation represents **production-grade code** versus **throw-away scripts**.
