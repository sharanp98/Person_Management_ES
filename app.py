from flask import Flask, request, jsonify, render_template
from elasticsearch import Elasticsearch
from elasticsearch.exceptions import NotFoundError
from flask_cors import CORS
import re
from elasticsearch.helpers import bulk  # Import bulk from helpers module

app = Flask(__name__)
CORS(app)
es = Elasticsearch("http://localhost:9200", basic_auth=('elastic', 'password'), verify_certs=False)

INDEX_NAME = "people_index"

# Create index with mapping for fields
def create_index():
    if not es.indices.exists(index=INDEX_NAME):
        es.indices.create(index=INDEX_NAME, mappings={
            "properties": {
                "name": {"type": "text"},
                "email": {"type": "text"},
                "bio": {"type": "text"}
            }
        })

create_index()

@app.route('/')
def index():
    return render_template('index.html')

# Data validation function
def validate_person_data(data):
    if 'name' not in data or len(data['name']) == 0:
        return "Name is required."
    if 'email' not in data or not re.match(r"[^@]+@[^@]+\.[^@]+", data['email']):
        return "Valid email is required."
    if 'age' in data and not isinstance(data['age'], int):
        return "Age must be an integer."
    return None

# Function to prepare data for bulk insert
def prepare_bulk_data(data):
    bulk_data = []
    for person in data:
        action = {
            "_op_type": "index",  # You can use "create" if you want to prevent overwriting existing docs
            "_index": INDEX_NAME,
            "_source": person
        }
        bulk_data.append(action)
    return bulk_data

# Bulk insert route
@app.route("/api/bulk_documents", methods=["POST"])
def bulk_insert_documents():
    data = request.json
    if not isinstance(data, list):
        return jsonify({"error": "Data must be a list of documents"}), 400
    
    # Prepare the data for bulk insertion
    bulk_data = prepare_bulk_data(data)

    try:
        success, failed = bulk(es, bulk_data)
        if success:
            return jsonify({"message": f"Successfully inserted {success} documents"}), 201
        else:
            return jsonify({"error": f"Failed to insert documents, {failed} failed"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
# Create a new document
@app.route("/api/documents", methods=["POST"])
def create_document():
    data = request.json
    validation_error = validate_person_data(data)
    if validation_error:
        return jsonify({"error": validation_error}), 400

    try:
        response = es.index(index=INDEX_NAME, document=data)
        return jsonify({"id": response["_id"], **data}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Read a document by ID
@app.route("/api/documents/<doc_id>", methods=["GET"])
def get_document(doc_id):
    try:
        response = es.get(index=INDEX_NAME, id=doc_id)
        return jsonify({"id": doc_id, **response["_source"]}), 200
    except NotFoundError:
        return jsonify({"error": "Document not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Update an existing document
@app.route("/api/documents/<doc_id>", methods=["PUT"])
def update_document(doc_id):
    data = request.json
    validation_error = validate_person_data(data)
    if validation_error:
        return jsonify({"error": validation_error}), 400

    try:
        response = es.update(index=INDEX_NAME, id=doc_id, doc=data)
        updated_doc = es.get(index=INDEX_NAME, id=doc_id)
        return jsonify({"id": doc_id, **updated_doc["_source"]}), 200
    except NotFoundError:
        return jsonify({"error": "Document not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Delete a document by ID
@app.route("/api/documents/<doc_id>", methods=["DELETE"])
def delete_document(doc_id):
    try:
        response = es.delete(index=INDEX_NAME, id=doc_id)
        return jsonify({"message": "Document deleted successfully"}), 200
    except NotFoundError:
        return jsonify({"error": "Document not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Search for documents by a query
@app.route("/api/search", methods=["GET"])
def search_documents():
    query = request.args.get("query")
    sort = request.args.get("sort", "_score")
    page = int(request.args.get("page", 1))
    size = int(request.args.get("size", 10))
    
    if not query:
        return jsonify({"error": "Query parameter is required"}), 400

    search_query = {
        "query": {
            "multi_match": {
                "query": query,
                "type": "best_fields",
                "fields": ["name", "email", "bio"]
            }
        },
        "from": (page - 1) * size,
        "size": size,
        "sort": [
            {sort: {"order": "desc"}}
        ]
    }

    try:
        response = es.search(index=INDEX_NAME, body=search_query)
        results = [{"id": hit["_id"], **hit["_source"]} for hit in response["hits"]["hits"]]
        return jsonify(results), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
# Retrieve all records (without pagination)
@app.route("/api/documents", methods=["GET"])
def get_all_documents():
    filter_field = request.args.get("filter_field")
    filter_value = request.args.get("filter_value")
    sort = request.args.get("sort", "_score")

    # Query body without pagination settings
    query_body = {
        "size": 10000,  # or set to an estimated max number of records
        "sort": [
            {sort: {"order": "desc"}}
        ]
    }

    if filter_field and filter_value:
        query_body["query"] = {
            "match": {filter_field: filter_value}
        }
    else:
        query_body["query"] = {"match_all": {}}

    try:
        response = es.search(index=INDEX_NAME, body=query_body)
        results = [{"id": hit["_id"], **hit["_source"]} for hit in response["hits"]["hits"]]
        return jsonify(results), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    

# Bulk indexing endpoint (for batch processing)
@app.route("/api/documents/bulk", methods=["POST"])
def bulk_index_documents():
    data = request.json
    if not isinstance(data, list):
        return jsonify({"error": "Request body must be a list of documents."}), 400

    bulk_data = []
    for doc in data:
        validation_error = validate_person_data(doc)
        if validation_error:
            return jsonify({"error": validation_error}), 400
        
        bulk_data.append({
            "_op_type": "index",
            "_index": INDEX_NAME,
            "_source": doc
        })

    try:
        es.bulk(index=INDEX_NAME, body=bulk_data)
        return jsonify({"message": "Bulk documents indexed successfully."}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)
