const connection = require('../database/connection');

module.exports = {

    async index(request, response)  {
        const {login} = request.body;

        const ongs = await connection('ongs').select('name').where('id', login).first();
        if (!ongs){
           return response.status(400).json({ error: 'No ONG found with this ID' });
        }
        return response.json( ongs );
    }
}