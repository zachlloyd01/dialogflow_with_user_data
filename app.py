'''
    Get JSON files of Google auth data.

    dialogflowconfig.json is the json of the service account for dialogflow

    fbAdminConfig.json is the admin config for firebase auth

    fbconfig.json is the main firebase config
'''


from flask import Flask, request, jsonify
from functools import wraps
import pyrebase
import json
import firebase_admin
from firebase_admin import credentials, auth, db
import os
import dialogflow
from google.api_core.exceptions import InvalidArgument

app = Flask(__name__) # Create a Flask instance

# Connect to firebase
cred = credentials.Certificate('fbAdminConfig.json')
firebase = firebase_admin.initialize_app(cred, {
    'databaseURL': json.load(open('fbconfig.json'))['databaseURL']
})
pb = pyrebase.initialize_app(json.load(open('fbconfig.json')))

# Connect to DialogFlow
with open('dialogflowconfig.json') as f: # Open service account
    raw_data = json.load(f) # load to JSON
    DIALOGFLOW_PROJECT_ID = raw_data['project_id'] # Set Project ID
    DIALOGFLOW_LANGUAGE_CODE = 'en-us' # Set Language Code

    f.close()

os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = "dialogflowconfig.json" # Set Google auth credentials to service account file

session_client = dialogflow.SessionsClient() # Sessioning client

def check_token(f): # Middleware function to check authorization
    @wraps(f)
    def wrap(*args, **kwargs): 
        if not request.headers.get('authorization'):
            return {'message': 'No token provided'},401
        try:
            user = auth.verify_id_token(request.headers['authorization']) # Verify login token against Google
            request.user = user # Attach user to finished request
        except:
            return {'message':'Invalid token provided.'},401

        return f(*args, **kwargs) # Return the middleware
    return wrap # Return the whole wrapper

@app.route('/api/signup', methods=['POST']) # Signup path
def signup():

    data = request.get_json() # Pull data from request

    email = data['email']
    password = data['password']

    if email is None or password is None: # If no email or password
        return {'message': 'Error missing email or password'},401

    try:
        user = auth.create_user( # Create new user in FireBase
                email=email,
                password=password
            )
        return {'message': f'Successfully created user {user.uid}'},200 # Return success
    except:
            return {'message': 'Error creating user'},500 # No user created

@app.route('/api/signin',methods=['POST']) # Sign in to app
def signin():
    data = request.get_json()

    email = data['email']
    password = data['password']

    try:
        user = pb.auth().sign_in_with_email_and_password(email, password) # Check user
        jwt = user['idToken'] # Generate new JWT
        return {'token': jwt}, 200 # Return new JWT

    except:
        return {'message': 'There was an error logging in'},500

@app.route('/api/sendchatmessage', methods=['POST']) # Send message to the bot
@check_token
def sendchatmessage():
    session_id = request.user['uid'] # Get session from ID for dialogflow
    session = session_client.session_path(DIALOGFLOW_PROJECT_ID, session_id) # Create/Get session
    in_text = request.get_json()['message'] # Get user input

    text_input = dialogflow.types.TextInput(text=in_text, language_code=DIALOGFLOW_LANGUAGE_CODE) # generate new input to bot
    query_input = dialogflow.types.QueryInput(text=text_input) # Query bot
    try:
        response = session_client.detect_intent(session=session, query_input=query_input) # Get bot response
        # Add messages to firebase
        ref = db.reference('messages')
        ref.child(request.user['uid']).push({
            'from': 'user',
            'message': in_text
        })
        ref.child(request.user['uid']).push({
            'from': 'bot',
            'message': response.query_result.fulfillment_text
        })
    except InvalidArgument:
        return { 'error': 'Invalid Argument' }, 500

    return { 'response': response.query_result.fulfillment_text }, 200

@app.route('/api/adduserdata', methods=['POST']) # Add data to a given user (supports scaling)
@check_token
def adduserdata():
    data = request.get_json()
    
    ref = db.reference('users')

    for updated in data:

        ref.child(request.user['uid']).update({
            updated: data[updated]
        })


    return db.reference(f'/users/{request.user["uid"]}').get(), 200

@app.route('/api/user', methods=['GET']) # Get data for signed in user
@check_token
def getuserdata():
    try:
        return db.reference(f'/users/{request.user["uid"]}').get(), 200
    except:
        return {'error': 'server error'}, 500

@app.route('/api/usermessages', methods=['GET']) # Get all messages for signed in user
@check_token
def getusermessages():
    try:
        if db.reference(f'/messages/{request.user["uid"]}').get() is None:
            return {}, 200
        return db.reference(f'/messages/{request.user["uid"]}').get(), 200
    except:
        return {'error': 'server error'}, 500

app.run(debug=False)