django-deploy-tools
===================
This is fabric script for painless django deployment. My setup uses nginx, supervisord, gunicorn, celery and celerycam. This script is oriented on bitbucket Git hosting.

Everything is done with newly created user named corresponding to the host name deploying to.

There are 2 fabric tasks: deployment and update\_source.

# Deployment
```
fab deploy:host=username@host
```
This will run full deployment routine:
 * Copy bitbucket deployment key named as `keys/bitbucket-deployment.key` to remote machine
 * Clone/update Git repo.
 * Create virtualenv and install packages from pip requirements file
 * Update django settings file
 * Update service templates with correct paths/username and copy them to the system
 * Collect django static files
 * Create database with syncdb or migrate if it is already created
 * Start or restart services

# Source code update
```
fab update_source:host=username@host
```
This will run short routine to update code base and corresponding things:
 * Update from Git repo
 * Install packages from pip requirements file
 * Update django settings file
 * Collect django static files
 * Migrate database
 * Restart services

# Parameters
There are 2 parameters:
 * `branch` - used to specify branch to clone
 * `staging` - specifies that we are working with staging server, so some config changes are made
