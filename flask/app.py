#================================================================
# File: app.py
# Desc: flask app
#================================================================
import flask
from flask_cors import CORS
from datetime import datetime
import logging
from route import *
import argparse    

#================================================================
# parse arguments
#================================================================
parser = argparse.ArgumentParser()
parser.add_argument("--host",       default='0.0.0.0')
parser.add_argument("--port",       default=8011)
parser.add_argument("--cert-file",  default=None)
parser.add_argument("--key-file",   default=None)
args = parser.parse_args()

#================================================================
# setup
#================================================================
# disabling default logger
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# app setup
app = flask.Flask(__name__)
# cors = CORS(app, supports_credentials=True)
cors = CORS(
    app,
    origins="*",  # allow your Next.js dev server
    supports_credentials=True,
    methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["Content-Type", "Authorization"]
)
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024
app.config['CORS_HEADERS'] = 'Content-Type'
app.config['SECRET_KEY'] = 'ihaveabigone'


#================================================================
# print traffic
#================================================================
@app.before_request
def __before_req(**kwargs):
    path:str = flask.request.path
    params = flask.request.args.to_dict()
    visitor = flask.request.headers.get("X-Real-IP")
    method = flask.request.method
    
    t = datetime.now().strftime("%H:%M:%S")
    print("[%s] %s//%s -- %s - %s" %(t, visitor, method ,path, params))
    
    
    
#================================================================
# register blueprints or traffic
#================================================================
base = flask.Blueprint('base', __name__, url_prefix='/api')
base.register_blueprint(system.bp, url_prefix="/system")
app.register_blueprint(base)

#================================================================
# run time!
#================================================================
context = (args.cert_file,  args.key_file) if args.key_file and args.cert_file else None
# context = ("/home/nosnhoj/.cert/cert.pem","/home/nosnhoj/.cert/key.pem")

if __name__ == "__main__": 
    print("=========================================================================")
    print(f">> Server running at {args.host}:{args.port}")
    # app.run(host=args.host, port=args.port, ssl_context=context, use_reloader=True)
    app.run(host=args.host, port=args.port, ssl_context=context, use_reloader=False)
    
    
    