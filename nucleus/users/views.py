from flask import redirect, url_for
from flask.ext.login import login_user, logout_user, current_user, login_required
from flask import request, render_template, redirect, url_for, flash
import requests
import urllib2
from models import User
from nucleus.app import DB
from sqlalchemy.exc import IntegrityError

def landing():
	# if current_user.is_authenticated:
	# 	return redirect(url_for('dashboard'))
	return render_template("static_pages/index.html")

def dashboard():
	return render_template('users/dashboard.html')

def callback():
	url = 'https://my.mlh.io/oauth/token?client_id=61d0d7bf56ab02f4a0dcdddc26816c27164748890de08ddd809877ba3f229b15&client_secret=67a6dcad88e1a881934518f5abc6beba46fc6910756b7f1c2a85f7dafd0bf5a7&code='+ request.args.get('code')+ '&redirect_uri=http%3A%2F%2F127.0.0.1%3A5000%2Fcallback&grant_type=authorization_code'
	resp = requests.post(url)
	# print resp.headers
	access_token = resp.json()['access_token']
	user = User.query.filter_by(email=access_token).first()
	if user is None:
		# create the user
		try:
			user_info = requests.get('https://my.mlh.io/api/v1/user?access_token={0}'.format(access_token)).json()
			user = User(user_info)
			DB.session.add(user)
			DB.session.commit()
		except IntegrityError:
			# a unique value already exists this should never happen
			DB.session.rollback()
			flash('A fatal error occurred. Please contact us for help', 'error')
			return render_template('static_pages/index.html')
	else:
		login_user(user.first(), remember=True)
		return render_template('users/dashboard.html')
	return redirect(url_for('confirm-registration'))
	# return 'Access token for current user: ' + access_token

@login_required
def confirm_registration():
	if request.method == 'GET':
		return render_template('users/confirm.html', user=current_user)
	else:
		return 'POST REQUEST'