from fabric.contrib.files import append, exists, sed
from fabric.api import env, local, run, put, sudo
import random

env.key_filename = '/path/to/ssh/key'

DJANGO_PROJECT_NAME = 'project'
REPO_URL = ('git@bitbucket.org:user/project.git')

def deploy(branch=None, staging=False):
    site_folder = '/sites/%s' % (env.host)
    source_folder = site_folder + '/source'
    deploy_folder = source_folder + '/deploy'
    initial_data_folder = site_folder + '/initial_data'
    django_project_folder = source_folder+'/'+DJANGO_PROJECT_NAME
    service_username = DJANGO_PROJECT_NAME
    configs_folder = deploy_folder+'/configs'
    configs = [configs_folder+'/nginx-config-template.conf',
               configs_folder+'/supervisord.conf',
               configs_folder+'/supervisord/celeryd.conf',
               configs_folder+'/supervisord/celerycam.conf',
               configs_folder+'/supervisord/gunicorn.conf', ]

    _copy_deployment_key(deploy_folder)
    _get_latest_source(source_folder, branch)
    _update_settings(source_folder, env.host, DJANGO_PROJECT_NAME)
    if staging:
        _change_celery_broker_url(source_folder, env.host, DJANGO_PROJECT_NAME)
    _update_virtualenv(source_folder)
    _update_static_files(django_project_folder)
    _update_database(django_project_folder)
    _update_config_templates(configs, site_folder, deploy_folder,
                             django_project_folder, env.host, service_username)
    _copy_nginx_config(configs[0], env.host)
    _copy_supervisord_configs(configs_folder+'/supervisord', env.host)
    _create_log_dirs(site_folder)
    _create_user(service_username)
    _update_owner(site_folder, service_username)
    _restart_services()

def update_source(branch=None):
    site_folder = '/sites/%s' % (env.host)
    source_folder = site_folder + '/source'
    service_username = DJANGO_PROJECT_NAME

    _get_latest_source(source_folder, branch)
    _update_settings(source_folder, env.host, DJANGO_PROJECT_NAME)
    _update_owner(site_folder, service_username)
    _restart_services()

def _copy_deployment_key(deploy_folder):
    key_file_name = DJANGO_PROJECT_NAME+'_deployment.key'
    if not exists('~/.ssh'):
        run('mkdir -p ~/.ssh && chmod 700 ~/.ssh')
    if not exists('~/.ssh/'+key_file_name):
        put('keys/bitbucket-deployment.key', 
            '~/.ssh/'+key_file_name)
        run('chmod 600 ~/.ssh/'+key_file_name)

    bitbucket_config = ('Host bitbucket.org\n'
                        '    HostName bitbucket.org\n'
                        '    IdentityFile ~/.ssh/'+key_file_name+'\n')
    run('echo "%s" >> ~/.ssh/config' % bitbucket_config)

def _get_latest_source(source_folder, branch):
    if exists(source_folder + '/.git'):
        run('cd %s && git fetch' % (source_folder,))
    else:
        if branch:
            run('git clone -b %s %s %s' % (branch, REPO_URL, source_folder))
        else:
            run('git clone %s %s' % (REPO_URL, source_folder))
    current_commit = local("git log -n 1 --format=%H", capture=True)
    run('cd %s && git reset --hard %s' % (source_folder, current_commit))

def _update_settings(source_folder, site_name, project_name):
    settings_path = source_folder + '/{0}/{0}/settings.py'.format(project_name)
    sed(settings_path, "DEBUG = True", "DEBUG = False")
    sed(settings_path, 'DOMAIN = .+$', 'DOMAIN = "%s"' % (site_name,))
    sed(settings_path,
        'ALLOWED_HOSTS =.+$',
        'ALLOWED_HOSTS = ["{0}", "www.{0}", ]'.format(site_name)
    )
    secret_key_file = source_folder+'/{0}/{0}/secret_key.py'.format(project_name)
    if not exists(secret_key_file):
        chars = 'abcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*(-_=+)'
        key = ''.join(random.SystemRandom().choice(chars) for _ in range(50))
        append(secret_key_file, "SECRET_KEY = '%s'" % (key,))
    append(settings_path, '\nfrom .secret_key import SECRET_KEY')

def _change_celery_broker_url(source_folder, site_name, project_name):
    settings_path = source_folder + '/{0}/{0}/celery.py'.format(project_name)
    sed(settings_path, 'CELERY_RESULT_BACKEND = "redis://localhost:6379/0"',
                       'CELERY_RESULT_BACKEND = "redis://localhost:6379/1"')
    sed(settings_path, 'BROKER_URL = "redis://localhost:6379/0"',
                       'BROKER_URL = "redis://localhost:6379/1"')

def _update_config_templates(configs, virtualenv_folder, deploy_folder, 
                             project_folder, site_name, user_name):
    for config in configs:
        sed(config, "SITE_NAME", site_name)
        sed(config, "USER", user_name)
        sed(config, "PROJECT_NAME", DJANGO_PROJECT_NAME)
        sed(config, "PROJECT_DIRECTORY", project_folder)
        sed(config, "VIRTUALENV_DIRECTORY", virtualenv_folder)
        sed(config, "DEPLOY_DIRECTORY", deploy_folder)

def _copy_nginx_config(config_file, site_name):
    path_to_nginx = '/etc/nginx'
    nginx_config_name = path_to_nginx+'/sites-available/'+site_name

    sudo('cp '+config_file+' '+nginx_config_name)
    sudo('ln -fs '+nginx_config_name+' '+path_to_nginx+'/sites-enabled/'+site_name)

def _copy_supervisord_upstart_config(config_file):
    sudo('cp '+config_file+' /etc/init/supervisord.conf')

def _copy_supervisord_configs(supervisor_config_dir, site_name):
    config_dir = '/etc/supervisor/conf.d/{}'.format(site_name)
    sudo('mkdir {}'.format(config_dir))
    sudo('cp '+supervisor_config_dir+'/*.conf'+' '+config_dir+'/')

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
    run('mv {0}/main/fixtures/deploy_initial_data.json '
        '{0}/main/fixtures/initial_data.json'.format(project_folder))
    if exists(project_folder + 'db.sqlite3'):
        run('cd %s && ../../bin/python '
            'manage.py migrate --noinput' % (project_folder))
    else:
        run('cd %s && ../../bin/python '
            'manage.py syncdb --all --noinput' % (project_folder))

def _create_log_dirs(virtualenv_folder):
    run('mkdir -p '+virtualenv_folder+'/logs')

def _restart_services():
    sudo('supervisorctl reread')
    sudo('supervisorctl update')

    if not run('pgrep supervisord'):
        sudo('service start supervisord')
    else:
        print "Supervisord already running"
        sudo('supervisorctl restart gunicorn-{}'.format(DJANGO_PROJECT_NAME))

    if not run('pgrep nginx'):
        sudo('service nginx start')
    else:
        print "Nginx already running"
        sudo('service nginx reload')

def _create_user(user_name):
    if not run('id -u '+user_name):
        sudo('adduser --disabled-password '+user_name)
        sudo('usermod -a -G www-data '+user_name)

def _update_owner(site_folder, user_name):
    sudo('chown -R '+user_name+':www-data '+site_folder)
