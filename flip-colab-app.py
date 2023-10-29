import datetime
import os
import time
import threading
import uuid
from flask import Flask, render_template, request, url_for, redirect, g
from flask_admin import Admin, AdminIndexView, expose, helpers
from flask_admin.contrib.sqla import ModelView
from flask_sqlalchemy import SQLAlchemy
from flask_babel import Babel
from flask_login import UserMixin, LoginManager, current_user, login_user, logout_user
from wtforms import form, fields, validators
from pytube import YouTube
import whisper
from open_ai_utils import get_summary_using_openai, run_question_answer


whisper_model = whisper.load_model("tiny")

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = '6ae472c6-ea84-48a7-ad5d-2be9118ad565'

babel = Babel(app)
db = SQLAlchemy(app)
login = LoginManager(app)


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(50))
    last_name = db.Column(db.String(50))
    email = db.Column(db.String(50), unique=True)
    password = db.Column(db.String(50))

    @property
    def username(self):
        return f'{self.first_name} {self.last_name}'


@login.user_loader
def load_user(email):
    return User.query.get(email)


class LoginForm(form.Form):
    email = fields.StringField(validators=[validators.InputRequired()])
    password = fields.PasswordField(validators=[validators.InputRequired()])

    def validate_login(self, field):
        user = self.get_user()
        if user is None:
            raise validators.ValidationError('Invalid user')
        if user.password != self.password.data:
            raise validators.ValidationError('Invalid password')

    def get_user(self):
        return db.session.query(User).filter_by(email=self.email.data).first()


class Video(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(1024))
    author = db.Column(db.String(512))
    url = db.Column(db.String(512))
    thumbnail_url = db.Column(db.String(64))
    views = db.Column(db.Integer)
    length = db.Column(db.Integer)
    transcript_status = db.Column(db.String(64))
    transcript = db.Column(db.Text)
    summary = db.Column(db.Text)
    created_on = db.Column(db.DateTime)
    unique_id = db.Column(db.String(28), unique=True)


class HomeIndexView(AdminIndexView):
    @expose('/')
    def index(self):
        is_authenticated = current_user.is_authenticated
        username = current_user.username if is_authenticated else None
        return self.render('admin/index.html', is_authenticated=is_authenticated, username=username)

    @expose('/login/', methods=('GET', 'POST'))
    def login_view(self):
        loging_error = None
        if request.method == 'POST':
            email = request.form['formemail']
            password = request.form['formpassword']
            user = db.session.query(User).filter_by(email=email).filter_by(password=password).first()
            if user:
                login_user(user)
            else:
                loging_error = 'Invalid email address or password. Try again.'
            if current_user.is_authenticated:
                return redirect(url_for('.index'))

        return render_template('admin/login.html', loging_error=loging_error)

    @expose('/register/', methods=('GET', 'POST'))
    def register_view(self):
        register_error = None
        if request.method == 'POST':
            first_name = request.form['formfname']
            last_name = request.form['formlname']
            email = request.form['formemail']
            password = request.form['formpassword']
            existing_user = db.session.query(User).filter_by(email=email).first()
            if existing_user:
                register_error = 'Email address already exists. Try logging in instead.'
                return render_template('admin/register.html', register_error=register_error)

            user = User(first_name=first_name, last_name=last_name, email=email, password=password)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            if current_user.is_authenticated:
                return redirect(url_for('.index'))

        return render_template('admin/register.html')

    @expose('/logout/')
    def logout_view(self):
        logout_user()
        return redirect(url_for('.index'))


admin = Admin(app, name='flip-colab', index_view=HomeIndexView(url='/flipcolab'))

class VideoModelView(ModelView):
    list_template = 'video_list_template.html'
    create_template = 'video_create_template.html'
    details_template = 'video_details_template.html'
    can_view_details = True
    can_create = True
    can_delete = True
    can_edit = False
    column_list = ['title', 'author', 'url', 'transcript_status', 'created_on']
    form_columns = ['url']
    column_details_list = ['url', 'title', 'author', 'transcript', 'summary']
    #form_excluded_columns = ('title', 'author', 'views', 'transcript_status', 'created_on')
    column_formatters = dict(
        views = lambda v, c, m, p: f'{m.views:,} Views',
        length = lambda v, c, m, p: time.strftime('%H:%M:%S', time.gmtime(m.length)),
        created_on=lambda v, c, m, p: m.created_on.strftime('%Y-%m-%d %H:%M:%S')
    )
    column_default_sort = ('created_on', True)

    def is_accessible(self):
        # return current_user.is_authenticated
        return True

    @expose('/')
    def index_view(self):
        self._template_args['username'] = current_user.username
        self._template_args['home_highlight'] = False
        self._template_args['browse_topic_highlight'] = True
        self._template_args['create_new_highlight'] = False
        return super().index_view()

    @expose('/details/')
    def details_view(self):
        self._template_args['username'] = current_user.username
        self._template_args['user_names'] = [row[0] + ' '+ row[1] for row in db.engine.execute("SELECT first_name, last_name FROM user")]
        return super().details_view()

    @expose('/new/', methods=('GET', 'POST'))
    def create_view(self):
        self._template_args['username'] = current_user.username
        self._template_args['home_highlight'] = False
        self._template_args['browse_topic_highlight'] = False
        self._template_args['create_new_highlight'] = True
        return super().create_view()
    
    @expose('/get_chat/')
    def get_chat(self):
        question = request.args.get('question')
        unique_id = request.args.get('uniqueId')
        context = db.engine.execute("SELECT transcript FROM video WHERE unique_id = :unique_id;", unique_id=unique_id).fetchone()['transcript']
        return run_question_answer(context, question)

    def on_model_change(self, form, model, is_created):
        model.title, model.author, model.thumbnail_url, model.views, model.length = self.get_youtube_video_details(model.url)
        model.transcript_status = 'Pending'
        model.created_on = datetime.datetime.utcnow()
        model.unique_id = uuid.uuid4().hex
        self.get_transcript(model.unique_id, model.url)

    @staticmethod
    def get_youtube_video_details(url):
        yt = YouTube(url)
        return yt.title, yt.author, yt.thumbnail_url, yt.views, yt.length

    @staticmethod
    def get_transcript(unique_id, url):
        os.makedirs('video_downloads', exist_ok=True)
        def generate_trascript(unique_id, url):
            print('Starting to download video...')
            audio_file = YouTube(url).streams.filter(only_audio=True).first().download(filename=f'video_downloads/{unique_id}.mp4')
            print('Running whisper model...')
            transcription = whisper_model.transcribe(audio_file)
            print(' whisper model done...')
            transcript = transcription['text']
            print('Starting summary...')
            summary = get_summary_using_openai(transcript)
            print('Finished summary...')
            db.engine.execute(
                "UPDATE Video SET transcript = :transcript, summary = :summary, transcript_status = 'Available' WHERE unique_id = :unique_id;",
                transcript=transcript,
                summary=summary,
                unique_id=unique_id
            )
        threading.Thread(target=generate_trascript, args=(unique_id, url)).start()


if __name__ == '__main__':
    admin.add_view(VideoModelView(Video, db.session))
    db.create_all()
    app.run()
