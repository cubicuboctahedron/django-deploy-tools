from fabric.contrib.files import append, exists, sed
from fabric.api import env, local, run, sudo
import random

env.key_filename = '/path/to/private/key.rsa'

DJANGO_PROJECT_NAME = 'example_project'
DJANGO_APP_NAME = 'main'
USERNAME = 'some_user'

REPO_URL = ('git@bitbucket.org:{}/{}.git').format(USERNAME, DJANGO_PROJECT_NAME)

def deploy():
    site_folder = '/sites/%s' % (env.host)
    source_folder = site_folder + '/source'
    deploy_folder = source_folder + '/deploy'
    django_folder = source_folder+'/'+DJANGO_PROJECT_NAME
    _get_latest_source(source_folder)
    _update_settings(source_folder, env.host, DJANGO_PROJECT_NAME)
    _update_virtualenv(source_folder)
    _update_static_files(django_folder)
    _update_database(django_folder)
    _update_configs(deploy_folder, env.host, env.user)
    _update_scraper(site_folder, scraper_folder, env.host)
    _start_services(env.host)

def _get_latest_source(source_folder):
    if exists(source_folder + '/.git'):
        run('cd %s && git fetch' % (source_folder,))
    else:
        run('git clone %s %s' % (REPO_URL, source_folder))
    current_commit = local("git log -n 1 --format=%H", capture=True)
    run('cd %s && git reset --hard %s' % (source_folder, current_commit))

def _update_settings(source_folder, site_name, project_name):
    settings_path = source_folder + '/{0}/{0}/settings.py'.format(project_name)
    sed(settings_path, "DEBUG = True", "DEBUG = False")
    sed(settings_path, 'DOMAIN = .+$', 'DOMAIN = "%s"' % (site_name,))
# removing debug toolbar from apps
    sed(settings_path, '"debug_toolbar",', '')
    sed(settings_path,
        'ALLOWED_HOSTS =.+$',
        'ALLOWED_HOSTS = ["%s"]' % (site_name,)  
    )
    secret_key_file = source_folder+'/{0}/{0}/secret_key.py'.format(project_name)
    if not exists(secret_key_file):
        chars = 'abcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*(-_=+)'
        key = ''.join(random.SystemRandom().choice(chars) for _ in range(50))
        append(secret_key_file, "SECRET_KEY = '%s'" % (key,))
    append(settings_path, '\nfrom .secret_key import SECRET_KEY')

def _update_virtualenv(source_folder):
    virtualenv_folder = source_folder + '/../'
    if not exists(virtualenv_folder + '/bin/pip'):
        run('virtualenv %s' % (virtualenv_folder,))

    run('%s/bin/pip install -r %s/requirements.txt' % (
            virtualenv_folder, source_folder
    ))

def _update_static_files(project_folder):
    run('cd %s && ../../bin/python '
        'manage.py collectstatic --noinput' % (project_folder))

def _update_database(project_folder):

    run('mv %s/{1}/fixtures/deploy_initial_data.json '
        '{2}/{1/fixtures/initial_data.json' % (DJANGO_APP_NAME, project_folder))

    if exists(project_folder + 'db.sqlite3'):
        run('cd %s && ../../bin/python '
            'manage.py migrate --noinput' % (project_folder))
    else:
        run('cd %s && ../../bin/python '
            'manage.py syncdb --all --noinput' % (project_folder))

def _update_configs(deploy_folder, site_name, user_name):
    nginx_config_template = deploy_folder+'/nginx-config-template.conf'
    path_to_nginx = '/etc/nginx'
    sed(nginx_config_template, "SITE_NAME", site_name)
    sed(nginx_config_template, "USER_NAME", user_name)
    sed(nginx_config_template, "PROJECT_NAME", DJANGO_PROJECT_NAME)
    sudo('cp '+nginx_config_template+\
        ' '+path_to_nginx+'/sites-available/'+site_name)
    sudo('ln -fs '+path_to_nginx+'/sites-available/'+site_name+\
        ' '+path_to_nginx+'/sites-enabled/'+site_name)

    gunicorn_config_template = deploy_folder+'/gunicorn-template.conf'
    sed(gunicorn_config_template, "SITE_NAME", site_name)
    sed(gunicorn_config_template, "PROJECT_NAME", DJANGO_PROJECT_NAME)
    sed(gunicorn_config_template, "USER_NAME", user_name)
    sudo('cp '+gunicorn_config_template+' /etc/init/gunicorn-'+site_name+'.conf')

def _start_services(site_name):
    try:
        sudo('sudo start gunicorn-'+site_name)
    except:
        print "Gunicorn already running, restarting"
        sudo('restart gunicorn-'+site_name)

    sudo('service nginx start')
    sudo('service nginx reload')
