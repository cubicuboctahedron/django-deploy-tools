from fabric.contrib.files import append, exists, sed
from fabric.api import env, local, run, put, sudo, settings, prefix
import random
import string

env.use_ssh_config = True

DJANGO_PROJECT_NAME = 'project name'
REPO_URL = ('git@bitbucket.org:user/project name.git')

def _configure(host, project_name, repo_url):
    config = {
        'project_name': project_name,
        'repo': repo_url,
        'user': string.replace(host, '.', '_'),
        'host': host,
    }

    config['nginx_folder'] = '/etc/nginx'
    config['venv_folder'] = '/sites/'+config['host']
    config['source_folder'] = config['venv_folder']+'/source'
    config['initial_data_folder'] = config['source_folder']+'/initial_data'
    config['deploy_folder'] = config['source_folder']+'/deploy'
    config['django_project_folder'] = config['source_folder']+'/'+config['project_name']
    config['django_settings_folder'] = config['django_project_folder']+'/'+config['project_name']
    config['configs_folder'] = config['deploy_folder']+'/configs'

    config['manage_cmd'] = (config['venv_folder']+'/bin/python '
                            +config['django_project_folder']+'/manage.py')

    config['configs'] = [config['configs_folder']+'/nginx-config-template.conf',
                         config['configs_folder']+'/supervisord.conf',
                         config['configs_folder']+'/supervisord/celeryd.conf',
                         config['configs_folder']+'/supervisord/celerycam.conf',
                         config['configs_folder']+'/supervisord/gunicorn.conf', ]

    return config

def deploy(branch=None, staging=False):
    config = _configure(env.host, DJANGO_PROJECT_NAME, REPO_URL)
    
    # as root
    _create_user(config)

    # as project user
    with settings(sudo_user=config['user']):
        _copy_deployment_key(config)
        _get_latest_source(config, branch)
        _update_settings(config)
        if staging:
           _change_celery_broker_url(config)
           _update_virtualenv(config)
        _update_static_files(config)
        _update_database(config)
        if staging:
            _load_fixtures(config, fixture='test_users.json')
        _load_fixtures(config, fixture='django_cms_data.json')
        _update_config_templates(config)
        if staging:
            _update_nginx_staging_template(config)
        _create_log_dirs(config)

    # as root
    _copy_nginx_config(config)
    _copy_supervisord_configs(config)
    _restart_services(config)

def update_source(branch=None, staging=False):
    config = _configure(env.host, DJANGO_PROJECT_NAME, REPO_URL)
    
    # as root
    _create_user(config)

    # as project user
    with settings(sudo_user=config['user']):
        _copy_deployment_key(config)
        _get_latest_source(config, branch)
        _update_settings(config)
        if staging:
           _change_celery_broker_url(config)
           _update_virtualenv(config)
        _update_static_files(config)
        _update_database(config)
        if staging:
            _load_fixtures(config, fixture='test_users.json')
        _load_fixtures(config, fixture='django_cms_data.json')

    # as root
    _restart_services(config)

def _create_user(config):
    if not exists('/home/'+config['user']):
        sudo('useradd -m -U '+config['user'])
        sudo('usermod -a -G www-data '+config['user'])
        """
        sudo('echo "source /usr/local/bin/virtualenvwrapper.sh" >> '
             '/home/{}/.profile'.format(config['user']), user=config['user'])
        sudo('echo "workon {}" >> /home/{}/.profile'.format(
            config['host'], config['user']), user=config['user'])
        """

def _copy_deployment_key(config):
    ssh_dir = '/home/{}/.ssh'.format(config['user'])
    key_file_name = config['project_name']+'_deployment.key'
    if not exists(ssh_dir):
        sudo('mkdir -p %s' % ssh_dir)
        sudo('chmod 700 %s' % ssh_dir)
    if not exists(ssh_dir+'/'+key_file_name):
        with settings(sudo_user='root'):
            put('keys/bitbucket-deployment.key', 
                ssh_dir+'/'+key_file_name, use_sudo=True, mode=0600)
            sudo('chown {user}:{group} {ssh_dir}/{key}'.format(
                user=config['user'], group=config['user'], 
                ssh_dir=ssh_dir, key=key_file_name))

    bitbucket_config = ('Host bitbucket.org\n'
                        '    HostName bitbucket.org\n'
                        '    IdentityFile '+ssh_dir+'/'+key_file_name+'\n')
    sudo('echo \''+bitbucket_config+'\' >> '+ssh_dir+'/config')

def _get_latest_source(config, branch):
    if exists(config['source_folder'] + '/.git'):
        sudo('cd %s && git fetch --recurse-submodules=yes' % config['source_folder'])
    else:
        if branch:
            sudo('git clone -b %s %s %s' % (branch, config['repo'], 
                                            config['source_folder']))
        else:
            sudo('git clone %s %s' % (config['repo'], config['source_folder']))
    current_commit = local("git log -n 1 --format=%H", capture=True)
    sudo('cd %s && git reset --hard %s' % (config['source_folder'], current_commit))

def _update_settings(config):
    settings_path = config['django_settings_folder']+'/settings.py'
    sed(settings_path, "DEBUG = True", "DEBUG = False", use_sudo=True)
    sed(settings_path, 'DOMAIN = .+$', 'DOMAIN = "%s"' % config['host'], use_sudo=True)
# removing debug toolbar from apps
    sed(settings_path, '"debug_toolbar",', '', use_sudo=True)
    sed(settings_path, '"debug_toolbar.middleware.DebugToolbarMiddleware",', '', use_sudo=True)
    sed(settings_path,
        'ALLOWED_HOSTS =.+$',
        'ALLOWED_HOSTS = ["{0}", "www.{0}", ]'.format(config['host']), use_sudo=True)
    secret_key_file = config['django_settings_folder']+'/secret_key.py'
    if not exists(secret_key_file):
        chars = 'abcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*(-_=+)'
        key = ''.join(random.SystemRandom().choice(chars) for _ in range(50))
        append(secret_key_file, "SECRET_KEY = '%s'" % (key,), use_sudo=True)
    append(settings_path, '\nfrom .secret_key import SECRET_KEY', use_sudo=True)

def _change_celery_broker_url(config):
    settings_path = config['django_settings_folder']+'/celery.py'
    sed(settings_path, 'CELERY_RESULT_BACKEND = "redis://localhost:6379/0"',
                       'CELERY_RESULT_BACKEND = "redis://localhost:6379/1"', use_sudo=True)
    sed(settings_path, 'BROKER_URL = "redis://localhost:6379/0"',
                       'BROKER_URL = "redis://localhost:6379/1"', use_sudo=True)

def _update_config_templates(config):
    for config_file in config['configs']:
        sed(config_file, "SITE_NAME", config['host'], use_sudo=True)
        sed(config_file, "USER", config['user'], use_sudo=True)
        sed(config_file, "PROJECT_NAME", config['project_name'], use_sudo=True)
        sed(config_file, "PROJECT_DIRECTORY", config['django_project_folder'], use_sudo=True)
        sed(config_file, "VIRTUALENV_DIRECTORY", config['venv_folder'], use_sudo=True)
        sed(config_file, "DEPLOY_DIRECTORY", config['deploy_folder'], use_sudo=True)

def _update_nginx_staging_template(config):
    sed(config['configs'][0], "www\.", "", use_sudo=True)

def _copy_nginx_config(config):
    nginx_config_name = config['nginx_folder']+'/sites-available/'+config['host']

    sudo('cp '+config['configs'][0]+' '+nginx_config_name)
    sudo('ln -fs '+nginx_config_name+' '
         +config['nginx_folder']+'/sites-enabled/'+config['host'])

def _copy_supervisord_upstart_config(config):
    sudo('cp '+config['config'][1]+' /etc/init/supervisord.conf')

def _copy_supervisord_configs(config):
    config_dir = '/etc/supervisor/conf.d/{}'.format(config['host'])
    sudo('mkdir -p {}'.format(config_dir))
    for config in config['configs'][2:]:
        sudo('cp '+config+' '+config_dir+'/')

def _update_virtualenv(config):
    if not exists(config['venv_folder'] + '/bin/pip'):
        sudo('virtualenv %s' % (config['venv_folder'],))

    sudo('%s/bin/pip install -r %s/requirements.txt' % (
            config['venv_folder'], config['source_folder']
    ))

def _update_static_files(config):
    sudo(config['manage_cmd']+' collectstatic --noinput')

def _update_database(config):
    sudo('mv {0}/main/fixtures/deploy_initial_data.json '
        '{0}/main/fixtures/initial_data.json'.format(config['django_project_folder']))
    if exists(config['django_project_folder'] + '/db.sqlite3'):
        sudo(config['manage_cmd']+' migrate --noinput')
    else:
        sudo(config['manage_cmd']+' syncdb --all --noinput')
        sudo(config['manage_cmd']+' migrate --fake')

def _load_fixtures(config, fixture):
    sudo(config['manage_cmd']+' loaddata '+config['initial_data_folder']+'/'+fixture)

def _create_log_dirs(config):
    sudo('mkdir -p '+config['venv_folder']+'/logs')

def _restart_services(config):
    sudo('supervisorctl reread')
    sudo('supervisorctl update')

    if not sudo('pgrep supervisord'):
        sudo('service start supervisord')
    else:
        print "Supervisord already running"
        sudo('supervisorctl restart gunicorn-'+config['host'])

    if not sudo('pgrep nginx'):
        sudo('service nginx start')
    else:
        print "Nginx already running"
        sudo('service nginx reload')

