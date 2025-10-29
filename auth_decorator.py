from flask import request, jsonify           
from functools import wraps                     
from firebase_admin import auth                 

# ================================================
# Decorator to require Firebase Authentication
# ================================================
def firebase_required(f):
    @wraps(f)  # Keeps the original function's metadata (name, docstring, etc.)
    def decorated_function(*args, **kwargs):
        token = None

        # Check for Authorization header (expected format: "Bearer <token>")
        if 'Authorization' in request.headers:
            token = request.headers['Authorization'].split("Bearer ")[-1]

        # If token is not provided, return 401 (unauthorized)
        if not token:
            return jsonify({'message': 'Missing token'}), 401

        try:
            # Verify the token using Firebase Admin SDK
            decoded_token = auth.verify_id_token(token)

            # Attach the authenticated user's UID to the request object
            request.user_uid = decoded_token['uid']

        except Exception as e:
            # If token verification fails, return 401 with error message
            return jsonify({'message': 'Invalid token', 'error': str(e)}), 401

        # Continue with the original function
        return f(*args, **kwargs)

    return decorated_function
