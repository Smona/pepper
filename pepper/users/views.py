from flask.ext.login import login_user, logout_user, current_user, login_required
from flask import request, render_template, redirect, url_for, flash, g
import requests
from models import User, UserRole
from pepper.app import DB
from sqlalchemy.exc import IntegrityError
from pepper import settings
import urllib2
# from pepper.utils import s3, send_email, s, roles_required, hs_client
from pepper.utils import s3, send_email, s, roles_required, ts
from helpers import send_status_change_notification, check_password, hash_pwd
import keen
from datetime import datetime

def landing():
	if current_user.is_authenticated:
		return redirect(url_for('dashboard'))
	return render_template("static_pages/index.html")

def login():
	return redirect(
		'https://my.mlh.io/oauth/authorize?client_id={0}&redirect_uri={1}callback&response_type=code'.format(
			settings.MLH_APPLICATION_ID, urllib2.quote(settings.BASE_URL)))

def login_local():
	if request.method == 'GET':
		if current_user.is_authenticated:
			return redirect(url_for('dashboard'))
		return render_template('users/login.html')
	else:
		email = request.form['email']
		password = request.form['password']
		user = User.query.filter_by(email=email).first()
		if user is None:
			flash("We couldn't find an account related with this email. Please verify the email entered.", "warning")
			return redirect(url_for('login_local'))
		elif user.password is None:
			flash('This account has not been setup yet. Please click the login link in your setup email.')
			return redirect(url_for('login_local'))
		elif not check_password(user.password, password):
			flash("Invalid Password. Please verify the password entered.", 'warning')
			return redirect(url_for('login_local'))

		user_role = UserRole.query.filter_by(user_id=user.id).first()
		if user_role is not None:
			flash("Invalid login portal, please login in again")
			return redirect(url_for('corp-login'))

		login_user(user, remember=True)
		flash('Logged in successfully!', 'success')
		return redirect(url_for('dashboard'))

def register_local():
	if not settings.REGISTRATION_OPEN:
		flash('Registration is currently closed', 'error')
		return redirect(url_for('landing'))
	if request.method == 'GET':
		return render_template('users/register_local.html')
	else: # Local registration
		user_info = {
				'email': request.form.get('email'),
				'first_name': request.form.get('fname'),
				'last_name': request.form.get('lname'),
				'password': request.form.get('password'),
				'type': 'local',
				'date_of_birth': request.form.get('date_of_birth'),
				'major': request.form.get('major'),
				'shirt_size': request.form.get('shirt_size'),
				'dietary_restrictions': request.form.get('dietary_restrictions'),
				'gender': request.form.get('gender'),
				'phone_number': request.form.get('phone_number'),
				'special_needs': request.form.get('special_needs'),
				'school_name': request.form.get('school_name')
		}

		if request.form.get('gender_other') != '' and user_info['gender'] == 'Other':
			user_info['gender'] = request.form.get('gender_other')
		
		user = User.query.filter_by(email=user_info['email']).first()
		if user is None:  # create the user
			g.log.info('Creating a user')
			g.log = g.log.bind(email=user_info['email'])
			g.log.info('Creating a new user from local information')
			user = User(user_info)
			DB.session.add(user)
			DB.session.commit()
			g.log.info('Successfully created user')

			token = s.dumps(user.email)
			url = url_for('confirm-account', token=token, _external=True)
			html = render_template('emails/confirm_account.html', link=url, user=user)
			send_email(settings.GENERAL_INFO_EMAIL, 'Confirm Your Account', user.email, None, html)
			login_user(user, remember=True)
		else: # Admin/Corporate need to login in from a different page
			flash('The account already exists, please login again', 'error')
			return redirect(url_for('login_local'))

		return redirect(url_for('confirm-registration'))

@login_required
def edit_profile():
	if request.method == 'GET':
		if current_user.type == 'MLH':
			return redirect("https://my.mlh.io/edit")
		elif current_user.type == 'local':
			return render_template('users/edit_profile.html', user=current_user)
	else:
		updated_user_info = {
				'email': request.form.get('email'),
				'first_name': request.form.get('fname'),
				'last_name': request.form.get('lname'),
				'password': request.form.get('new_password'),
				'type': 'local',
				'date_of_birth': request.form.get('date_of_birth'),
				'major': request.form.get('major'),
				'shirt_size': request.form.get('shirt_size'),
				'dietary_restrictions': request.form.get('dietary_restrictions'),
				'gender': request.form.get('gender'),
				'phone_number': request.form.get('phone_number'),
				'special_needs': request.form.get('special_needs'),
				'school_name': request.form.get('school_name')
		}
		if request.form.get('new_password') == '':
			updated_user_info['password'] = request.form.get('old_password')
		if not check_password(current_user.password, request.form.get('old_password')):
			flash('Profile update failed because of invalid Password. Please verify the password entered.', 'warning')
			return render_template('users/confirm.html', user=current_user)
		else:
			if request.form.get('gender_other') != '' and updated_user_info['gender'] == 'Other':
				updated_user_info['gender'] = request.form.get('gender_other')
			update_user_data('local', local_updated_info=updated_user_info)
			flash('Profile updated!', 'success')
			return redirect(url_for('dashboard'))

@login_required
def logout():
	logout_user()
	return redirect(url_for('landing'))

def callback():
	url = 'https://my.mlh.io/oauth/token'
	body = {
		'client_id': settings.MLH_APPLICATION_ID,
		'client_secret': settings.MLH_SECRET,
		'code': request.args.get('code'),
		'grant_type': 'authorization_code',
		'redirect_uri': settings.BASE_URL + "callback"
	}
	resp = requests.post(url, json=body)
	json = resp.json()
	
	if resp.status_code == 401:
		redirect_url = 'https://my.mlh.io/oauth/authorize?client_id={0}&redirect_uri={1}callback&response_type=code'.format(
			settings.MLH_APPLICATION_ID, urllib2.quote(settings.BASE_URL))
		
		g.log = g.log.bind(auth_code=request.args.get('code'), http_status=resp.status_code, resp=resp.text, redirect_url=redirect_url)
		g.log.error('Got expired auth code, redirecting: ')
		
		return redirect(redirect_url)
	
	if 'access_token' in json:
		access_token = json['access_token']
	else:
		g.log = g.log.bind(auth_code=request.args.get('code'), http_status=resp.status_code, resp=resp.text, body=body)
		g.log.error('Unable to get access token for user with:')
		return redirect(url_for('register_local'))
		# return render_template('layouts/error.html', title='MLH Server Error', message="We're having trouble pulling your information from MLH servers. Our tech team has been notified of the problem and we'll work with MLH to fix everything."), 505
	user = User.query.filter_by(access_token=access_token).first()
	if user is None:  # create the user
		try:
			g.log.info('Creating a user')
			user_info = requests.get('https://my.mlh.io/api/v1/user?access_token={0}'.format(access_token)).json()
			user_info['type'] = 'MLH'
			user_info['access_token'] = access_token
			g.log = g.log.bind(email=user_info['data']['email'])
			user = User.query.filter_by(email=user_info['data']['email']).first()
			if user is None:
				if settings.REGISTRATION_OPEN:
					g.log.info('Creating a new user from MLH info')
					user = User(user_info)
				else:
					flash('Registration is currently closed', 'error')
					return redirect(url_for('landing'))
			else:
				user.access_token = access_token
			DB.session.add(user)
			DB.session.commit()
			g.log.info('Successfully created user')
			login_user(user, remember=True)
		except IntegrityError:
			# a unique value already exists this should never happen
			DB.session.rollback()
			flash('A fatal error occurred. Please contact us for help', 'error')
			return render_template('static_pages/index.html')
		except Exception:
			g.log.error('Unable to create the user')
	else:
		login_user(user, remember=True)
		return redirect(url_for('dashboard'))
	return redirect(url_for('confirm-registration'))

def confirm_account(token):
	try:
		email = s.loads(token)
		user = User.query.filter_by(email=email).first()
		user.confirmed = True
		DB.session.add(user)
		DB.session.commit()
		flash('Successfully confirmed account', 'success')
		return redirect(url_for('confirm-registration'))
	except:
		return render_template('layouts/error.html', message="That's an invalid link. Please contact {} for help.".format(settings.GENERAL_INFO_EMAIL)), 401

@login_required
def confirm_registration():
	if not settings.REGISTRATION_OPEN:
		g.log = g.log.bind(email=current_user.email, access_token=current_user.access_token)
		g.log.info('Applications closed user redirected to homepage')
		flash('Registration is currently closed', 'error')
		logout_user()
		return redirect(url_for('landing'))
	if request.method == 'GET':
		if current_user.status != 'NEW':
			return redirect(url_for('dashboard'))
		elif current_user.confirmed == False:
			return render_template('layouts/error.html', title='Confirm Account', message='You need to confirm your account before proceeding'), 403
		return render_template('users/confirm.html', user=current_user)
	else:
		skill_level = request.form.get('skill-level')
		num_hackathons = request.form.get('num-hackathons')
		if int(num_hackathons) > 9223372036854775807:
			flash("{} seems like a lot of hackathons! I don't think you've been to that many".format(num_hackathons), 'error')
			return redirect(request.url)
		interests = request.form.get('interests')
		race_list = request.form.getlist('race')
		class_standing = request.form.get('class-standing')
		if request.form.get('mlh') != 'TRUE':
			flash('You must agree to MLH data sharing', 'error')
			return redirect(request.url)
		if None in (skill_level, num_hackathons, interests, race_list, class_standing):
			flash('You must fill out the required fields', 'error')
			return redirect(request.url)
		current_user.skill_level = skill_level
		current_user.num_hackathons = num_hackathons
		current_user.interests = interests
		current_user.race = 'NO_DISCLOSURE' if 'NO_DISCLOSURE' in race_list else ','.join(race_list)
		current_user.class_standing = class_standing
		current_user.time_applied = datetime.utcnow()
		if 'resume' in request.files:
			resume = request.files['resume']
			if is_pdf(resume.filename):  # if pdf upload to AWS
				s3.Object(settings.S3_BUCKET_NAME, 'resumes/{0}, {1} ({2}).pdf'.format(current_user.lname, current_user.fname, current_user.hashid)).put(Body=resume)
			else:
				flash('Resume must be in PDF format', 'error')
				return redirect(request.url)
		else:
			flash('Please upload your resume', 'error')
			return redirect(request.url)
		current_user.status = 'PENDING'
		DB.session.add(current_user)
		DB.session.commit()
		g.log = g.log.bind(email=current_user.email)
		g.log.info('User successfully applied')
		fmt = '%Y-%m-%dT%H:%M:%S.%f'
		keen.add_event('sign_ups', {
			'date_of_birth': current_user.birthday.strftime(fmt),
			'dietary_restrictions': current_user.dietary_restrictions,
			'email': current_user.email,
			'first_name': current_user.fname,
			'last_name': current_user.lname,
			'gender': current_user.gender,
			'id': current_user.id,
			'major': current_user.major,
			'phone_number': current_user.phone_number,
			'school': {
				'id': current_user.school_id,
				'name': current_user.school_name
			},
			'keen': {
				'timestamp': current_user.time_applied.strftime(fmt)
			},
			'interests': interests,
			'skill_level': skill_level,
			'races': race_list,
			'num_hackathons': num_hackathons,
			'class_standing': class_standing,
			'shirt_size': current_user.shirt_size,
			'special_needs': current_user.special_needs
		})

		# send a confirmation email
		html = render_template('emails/applied.html', user=current_user)
		send_email(settings.GENERAL_INFO_EMAIL, 'Thank you for applying to {0}'.format(settings.HACKATHON_NAME), current_user.email, txt_content=None, html_content=html)
		g.log.info('Successfully sent a confirmation email')

		flash('Congratulations! You have successfully applied for {0}! You should receive a confirmation email shortly'.format(settings.HACKATHON_NAME), 'success')

		return redirect(url_for('dashboard'))


def forgot_password():
	if request.method == 'GET':
		return render_template('users/forgot_password.html')
	else:
		email = request.form.get('email')
		user = User.query.filter_by(email=email).first()
		if user:
			token = ts.dumps(user.email, salt='recover-key')
			url = url_for('reset-password', token=token, _external=True)
			html = render_template('emails/reset_password.html', user=user, link=url)
			txt = render_template('emails/reset_password.txt', user=user, link=url)
			send_email('hello@hacktx.com', 'Your password reset link', email, txt, html)
		flash('If there is a registered user with {email}, then a password reset email has been sent!', 'success')
		return redirect(url_for('login_local'))

def reset_password(token):
	try:
		email = ts.loads(token, salt='recover-key', max_age=86400)
		user = User.query.filter_by(email=email).first()
	except:
		return render_template('layouts/error.html', error="That's an invalid link"), 401

	if request.method == 'GET':
		# find the correct user and log them in then prompt them for new password
		return render_template('users/reset_password.html')
	else:
		# take the password they've submitted and change it accordingly
		if user:
			if request.form.get('password') == request.form.get('password-check'):
				user.password = hash_pwd(request.form['password'])
				DB.session.add(user)
				DB.session.commit()
				login_user(user, remember=True)
				flash('Succesfully changed password!', 'success')
				return redirect(url_for('dashboard'))
			else:
				flash('You need to enter the same password in both fields!', 'error')
				return redirect(url_for('reset-password'), token=token)
		else:
			flash('Failed to reset password. This is an invalid link. Please contact us if this error persists', 'error')
			return redirect(url_for('forgot-password'))


def update_user_data(type, local_updated_info=None):
	if type == 'MLH':
		user_info = requests.get('https://my.mlh.io/api/v1/user?access_token={0}'.format(current_user.access_token)).json()
		if 'data' in user_info:
			current_user.email = user_info['data']['email']
			current_user.fname = user_info['data']['first_name']
			current_user.lname = user_info['data']['last_name']
			# current_user.class_standing = DB.Column(DB.String(255))
			current_user.major = user_info['data']['major']
			current_user.shirt_size = user_info['data']['shirt_size']
			current_user.dietary_restrictions = user_info['data']['dietary_restrictions']
			current_user.birthday = user_info['data']['date_of_birth']
			current_user.gender = user_info['data']['gender']
			current_user.phone_number = user_info['data']['phone_number']
			current_user.school_id = user_info['data']['school']['id']
			current_user.school_name = user_info['data']['school']['name']
			current_user.special_needs = user_info['data']['special_needs']
			DB.session.add(current_user)
			DB.session.commit()
	elif type == 'local' and local_updated_info is not None:
			current_user.email = local_updated_info['email']
			current_user.fname = local_updated_info['first_name']
			current_user.lname = local_updated_info['last_name']
			current_user.major = local_updated_info['major']
			current_user.shirt_size = local_updated_info['shirt_size']
			current_user.dietary_restrictions = local_updated_info['dietary_restrictions']
			current_user.birthday = local_updated_info['date_of_birth']
			current_user.gender = local_updated_info['gender']
			current_user.phone_number = local_updated_info['phone_number']
			current_user.school_name = local_updated_info['school_name']
			current_user.special_needs = local_updated_info['special_needs']
			current_user.password = hash_pwd(local_updated_info['password'])
			DB.session.add(current_user)
			DB.session.commit()



@login_required
def dashboard():
	if current_user.type == 'corporate':
		return redirect(url_for('corp-dash'))
	if current_user.status == 'NEW':
		update_user_data('MLH')
		return redirect(url_for('confirm-registration'))
	elif current_user.status == 'ACCEPTED':
		return redirect(url_for('accept-invite'))
	elif current_user.status == 'SIGNING':
		return redirect(url_for('sign'))
	elif current_user.status == 'CONFIRMED':
		return render_template('users/dashboard/confirmed.html', user=current_user)
	elif current_user.status == 'DECLINED':
		return render_template('users/dashboard/declined.html', user=current_user)
	elif current_user.status == 'REJECTED':
		return render_template('users/dashboard/rejected.html', user=current_user)
	elif current_user.status == 'WAITLISTED':
		return render_template('users/dashboard/waitlisted.html', user=current_user)
	elif current_user.status == 'ADMIN':
		users = User.query.order_by(User.created.asc())
		return render_template('users/dashboard/admin_dashboard.html', user=current_user, users=users)
	return render_template('users/dashboard/pending.html', user=current_user)


def is_pdf(filename):
	return '.' in filename and filename.lower().rsplit('.', 1)[1] == 'pdf'


@login_required
def accept():
	if current_user.status != 'ACCEPTED':  # they aren't allowed to accept their invitation
		message = {
			'NEW': "You haven't completed your application for {0}! Please submit your application before visiting this page!".format(settings.HACKATHON_NAME),
			'PENDING': "You haven't been accepted to {0}! Please wait for your invitation before visiting this page!".format(
				settings.HACKATHON_NAME),
			'CONFIRMED': "You've already accepted your invitation to {0}! We look forward to seeing you here!".format(
				settings.HACKATHON_NAME),
			'REJECTED': "You've already rejected your {0} invitation. Unfortunately, for space considerations you cannot change your response.".format(
				settings.HACKATHON_NAME),
			None: "Corporate users cannot view this page."
		}
		flash(message[current_user.status], 'error')
		return redirect(url_for('dashboard'))
	if request.method == 'GET':
			# for signature in med_signature_request.signatures:
			# 	embedded_obj = hs_client.get_embedded_object(signature.signature_id)
			# 	sign_url = embedded_obj.sign_url
		return render_template('users/accept.html', user=current_user)
	else:
		if 'accept' in request.form: #User has accepted the invite
			# if 'resume' in request.files:
			# 	resume = request.files['resume']
			# 	if is_pdf(resume.filename):  # if pdf upload to AWS
			# 		s3.Object('hacktx-pepper', 'resumes/{0}-{1}-{2}.pdf'.format(current_user.id, current_user.lname,
			# 																  current_user.fname)).put(Body=resume)
			# 		current_user.resume_uploaded = True
			# 	else:
			# 		flash('Resume must be in PDF format')
			# 		return redirect(url_for('accept-invite'))
			current_user.status = 'SIGNING'
			flash('You have successfully confirmed your invitation to {0}'.format(settings.HACKATHON_NAME))
		else:
			current_user.status = 'DECLINED'
		DB.session.add(current_user)
		DB.session.commit()
		return redirect(url_for('dashboard'))

@login_required
def sign():
	if current_user.status != 'SIGNING':  # they aren't allowed to accept their invitation
		message = {
			'NEW': "You haven't completed your application for {0}! Please submit your application before visiting this page!".format(settings.HACKATHON_NAME),
			'PENDING': "You haven't been accepted to {0}! Please wait for your invitation before visiting this page!".format(
				settings.HACKATHON_NAME),
			'CONFIRMED': "You've already accepted your invitation to {0}! We look forward to seeing you here!".format(
				settings.HACKATHON_NAME),
			'REJECTED': "You've already rejected your {0} invitation. Unfortunately, for space considerations you cannot change your response.".format(
				settings.HACKATHON_NAME),
			None: "Corporate users cannot view this page."
		}
		flash(message[current_user.status], 'error')
		return redirect(url_for('dashboard'))
	if request.method == 'GET':
		if current_user.med_auth_signature_id is None: # Generate the medical authorization waiver
			med_signature_request = hs_client.send_signature_request_embedded_with_template(
				test_mode=settings.DEBUG,
				client_id=settings.HELLO_SIGN_CLIENT_ID,
				template_id=settings.HELLO_SIGN_MED_WAIVER_TEMPLATE_ID,
				subject='Medical Authorization for {0} - {1} {2}'.format(settings.HACKATHON_NAME, current_user.fname, current_user.lname),
				message='Please sign the medical authorization waiver for UT Austin',
				signers=[
					{'role_name': 'Attendee', 'email_address': current_user.email, 'name': '{0} {1}'.format(current_user.fname, current_user.lname)}
				]
			)
			current_user.med_auth_signature_id = med_signature_request.signatures[0].signature_id
		if current_user.waiver_signature_id is None:
			waiver_signature_request = hs_client.send_signature_request_embedded_with_template(
				test_mode=settings.DEBUG,
				client_id=settings.HELLO_SIGN_CLIENT_ID,
				template_id=settings.HELLO_SIGN_WAIVER_TEMPLATE_ID,
				subject='Release Waiver for {0} - {1} {2}'.format(settings.HACKATHON_NAME, current_user.fname,
																		 current_user.lname),
				message='Please sign the release waiver for UT Austin',
				signers=[
					{'role_name': 'Attendee', 'email_address': current_user.email,
					 'name': '{0} {1}'.format(current_user.fname, current_user.lname)}
				]
			)
			current_user.waiver_signature_id = waiver_signature_request.signatures[0].signature_id

		DB.session.add(current_user)
		DB.session.commit()
		med_waiver_url = hs_client.get_embedded_object(current_user.med_auth_signature_id).sign_url
		release_waiver_url = hs_client.get_embedded_object(current_user.waiver_signature_id).sign_url
		return render_template('users/sign.html', user=current_user, sign_url=med_waiver_url)

@login_required
@roles_required('admin')
def create_corp_user():
	if request.method == 'GET':
		return render_template('users/admin/create_user.html')
	else:
		# Build a user based on the request form
		user_data = {'fname': request.form['fname'],
					 'lname': request.form['lname'],
					 'email': request.form['email']}
		user_data['type'] = 'corporate'
		user = User(user_data)
		DB.session.add(user)
		DB.session.commit()

		# send invite to the recruiter
		token = s.dumps(user.email)
		url = url_for('new-user-setup', token=token, _external=True)
		txt = render_template('emails/corporate_welcome.txt', user=user, setup_url=url)
		html = render_template('emails/corporate_welcome.html', user=user, setup_url=url)

		try:
			print txt
			if not send_email(from_email=settings.GENERAL_INFO_EMAIL,
							  subject='Your invitation to join my{}'.format(settings.HACKATHON_NAME),
							  to_email=user.email, txt_content=txt, html_content=html):
				print 'Failed to send message'
				flash('Unable to send message to recruiter', 'error')
		except ValueError as e:
			print e
		flash('You successfully create a new recruiter account.', 'success')
		return render_template('users/admin/create_user.html')


@login_required
@roles_required('admin')
def batch_modify():
	if request.method == 'GET':
		return 'Batch modify page'
	else:
		modify_type = request.form.get('type')
		if modify_type == 'fifo':
			accepted_attendees = User.query.filter_by(status='PENDING')  # TODO: limit by x
		else:  # randomly select n users out of x users
			x = request.form.get('x') if request.form.get(
				'x') is not 0 else -1  # TODO it's the count of users who are pending
			random_pool = User.query.filter
		# TODO: figure out how to find x random numbers


@login_required
@roles_required('admin')
def modify_user(hashid):
	# Send a post request that changes the user state to rejected or accepted
	user = User.get_with_hashid(hashid)
	user.status == request.form.get('status')
	DB.session.add(user)
	DB.session.commit()

	send_status_change_notification(user)


# Developers can use this portal to log into any particular user when debugging
def debug_user():
	if settings.DEBUG or (current_user.is_authenticated and current_user.status == 'ADMIN'):
		if current_user.is_authenticated:
			logout_user()
		if request.method == 'GET':
			return render_template('users/admin/internal_login.html')
		else:
			id = request.form['id']
			user = User.query.filter_by(id=id).first()
			if user is None:
				return 'User does not exist'
			login_user(user, remember=True)
			return redirect(url_for('landing'))
	else:
		return 'Disabled internal debug mode'


def initial_create():
	user_count = User.query.count()
	if user_count == 0:
		if request.method == 'GET':
			return render_template('users/admin/initial_create.html')
		else:
			user_info = {
				'email': request.form.get('email'),
				'fname': request.form.get('fname'),
				'lname': request.form.get('lname'),
				'password': request.form.get('password'),
				'type': 'admin'
			}
			user = User(user_info)
			user.status = 'ADMIN'
			DB.session.add(user)
			DB.session.commit()

			# add admin role to the user
			role = UserRole(user.id)
			role.name = 'admin'
			DB.session.add(role)
			DB.session.commit()

			return 'Successfully created initial admin user'
	else:
		return 'Cannot create new admin'
