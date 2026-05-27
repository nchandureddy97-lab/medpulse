import os
from flask import Flask, request, jsonify, send_from_directory, Response
import requests
from dotenv import load_dotenv

# Load env variables
load_dotenv()

FHIR_BASE_URL = os.getenv("FHIR_BASE_URL")
FHIR_AUTH_TOKEN = os.getenv("FHIR_AUTH_TOKEN")
PORT = int(os.getenv("PORT", 5000))

app = Flask(__name__, static_folder="public")

# Serve index.html by default
@app.route("/")
def serve_index():
    return send_from_directory(app.static_folder, "index.html")

# Serve other static files
@app.route("/<path:path>")
def serve_static(path):
    if os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, "index.html")

@app.route("/api/status")
def get_status():
    return jsonify({
        "fhir_base_url": FHIR_BASE_URL,
        "status": "connected" if FHIR_BASE_URL else "disconnected"
    })

@app.route("/api/fhir/<path:subpath>", methods=["GET", "POST", "PUT", "DELETE"])
def proxy_fhir(subpath):
    if not FHIR_BASE_URL or not FHIR_AUTH_TOKEN:
        return jsonify({
            "error": "FHIR configuration missing",
            "message": "FHIR_BASE_URL or FHIR_AUTH_TOKEN environment variables are not set. Please check your .env file."
        }), 500

    # Build destination URL
    url = f"{FHIR_BASE_URL.rstrip('/')}/{subpath}"
    
    # Forward query parameters
    params = request.args.to_dict(flat=False)
    params_flat = {k: v[0] if len(v) == 1 else v for k, v in params.items()}

    # Copy request headers, but replace Host and Authorization
    headers = {
        "Authorization": f"Bearer {FHIR_AUTH_TOKEN}",
        "Accept": "application/fhir+json, application/json",
        "Content-Type": request.content_type or "application/fhir+json"
    }

    try:
        # Perform the actual request to the FHIR server
        response = requests.request(
            method=request.method,
            url=url,
            headers=headers,
            params=params_flat,
            data=request.get_data(),
            timeout=30
        )
        
        # Create response back to client
        # Filter out transfer headers that Flask should handle
        excluded_headers = [
            "content-encoding", "content-length", "transfer-encoding", "connection"
        ]
        resp_headers = [
            (k, v) for k, v in response.headers.items() 
            if k.lower() not in excluded_headers
        ]
        
        return Response(response.content, response.status_code, resp_headers)

    except requests.exceptions.RequestException as e:
        return jsonify({
            "error": "FHIR Server connection failed",
            "message": str(e)
        }), 502

@app.route("/api/scribe/analyze", methods=["POST"])
def analyze_scribe():
    data = request.json or {}
    transcript = data.get("transcript", "").strip()
    patient_name = data.get("patientName", "Unknown Patient")
    
    if not transcript:
        return jsonify({"error": "Empty transcript"}), 400
        
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return jsonify({
            "error": "Gemini API Key missing",
            "message": "GEMINI_API_KEY environment variable is not set. Please add it to your .env file."
        }), 400
        
    prompt = f"""You are an advanced clinical AI assistant. You will analyze the following doctor-patient dialogue or clinician dictation for patient {patient_name} and extract structured medical artifacts.

Input transcript:
"{transcript}"

You must output a JSON object matching this schema:
{{
  "subjective": "Subjective summary of patient symptoms, history, concerns, and lifestyle inputs.",
  "objective": "Objective summary of physical findings, vital signs, labs, and diagnostic data mentioned.",
  "assessment": "Clinical assessment, suspected or confirmed diagnoses, and status.",
  "plan": "Step-by-step treatment plan, next steps, medications ordered, and follow-up timeline.",
  "instructions": "Plain-language patient-friendly care instructions, dietary guides, and warnings.",
  "icd10": [
    {{"code": "ICD-10 Code", "display": "Diagnosis Display Name"}}
  ],
  "rxnorm": [
    {{"code": "RxNorm Code", "display": "Medication Display Name"}}
  ]
}}
Ensure all descriptions are professional, concise, and clinically accurate. Do not include any markdown styling or wrapper other than raw JSON.
"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{
            "parts": [{
                "text": prompt
            }]
        }],
        "generationConfig": {
            "responseMimeType": "application/json"
        }
    }
    headers = {
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        res_data = response.json()
        
        # Extract text from Gemini response
        candidates = res_data.get("candidates", [])
        if not candidates:
            return jsonify({"error": "No AI output candidates returned"}), 502
            
        content_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        import json
        structured_data = json.loads(content_text)
        return jsonify(structured_data)
        
    except requests.exceptions.RequestException as e:
        return jsonify({
            "error": "Gemini API Connection Failed",
            "message": str(e)
        }), 502
    except Exception as e:
        return jsonify({
            "error": "Failed to parse AI output",
            "message": str(e)
        }), 500

if __name__ == "__main__":
    print(f"Starting FHIR Proxy server on http://localhost:{PORT}")
    print(f"Targeting FHIR Server: {FHIR_BASE_URL}")
    app.run(host="0.0.0.0", port=PORT, debug=os.getenv("FLASK_DEBUG", "true").lower() == "true")
