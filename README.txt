=================================================================================
==================================== Windows ====================================
=================================================================================
python -m venv venv
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
venv\Scripts\activate
pip install Flask PyMySQL Werkzeug Flask-SocketIO
pip install Flask-Cors Flask-Session SQLAlchemy
pip install flask_mail mail messages
pip install gunicorn
pip install -q -U google-generativeai
pip install python-dotenv
pip install pytz
pip install flask_cors
pip install apscheduler
pip install openai==0.27.2
pip install Pillow
pip install apscheduler
python.exe -m pip install --upgrade pip

#change this lines in the Flask to protect sensitive data from hacking from:
app.config['MAIL_USERNAME'] = os.environ.get('university.west.campus.link@gmail.com')
app.config['MAIL_PASSWORD'] = os.environ.get('hmuy zint phob fbdj')

#To 
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
#Then in the CMD when it inside the env set this lines:
set MAIL_USERNAME="university.west.campus.link@gmail.com"
set MAIL_PASSWORD="hmuy zint phob fbdj"

=================================================================================
================================= MacOS / Linux =================================
=================================================================================
python3 -m venv venv
source venv/bin/activate
sudo -s
pip install Flask PyMySQL Werkzeug Flask-SocketIO
pip install Flask-Cors Flask-Session SQLAlchemy
pip install flask_mail mail messages
pip install gunicorn
pip install -q -U google-generativeai
pip install python-dotenv
pip install pytz
pip install flask_cors
pip install apscheduler
pip install openai==0.27.2
pip install Pillow
pip install apscheduler
pip install --upgrade pip

#change this lines in the Flask to protect sensitive data from hacking from:
app.config['MAIL_USERNAME'] = os.environ.get('university.west.campus.link@gmail.com')
app.config['MAIL_PASSWORD'] = os.environ.get('hmuy zint phob fbdj')

#To 
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
#Then in the Terminal when it inside the env set this lines:
#export MAIL_USERNAME="university.west.campus.link@gmail.com"
#export MAIL_PASSWORD="hmuy zint phob fbdj"
