from django.db import models


class User(models.Model):
    STATUS_PENDING = 'PENDING_VERIFICATION'
    STATUS_ACTIVE = 'ACTIVE'
    STATUS_LOCKED = 'LOCKED'
    STATUS_DISABLED = 'DISABLED'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending Verification'),
        (STATUS_ACTIVE, 'Active'),
        (STATUS_LOCKED, 'Locked'),
        (STATUS_DISABLED, 'Disabled'),
    ]

    ROLE_OWNER = 'OWNER'
    ROLE_ADMIN = 'ADMIN'
    ROLE_ANALYST = 'ANALYST'
    ROLE_OPERATOR = 'OPERATOR'
    ROLE_VIEWER = 'VIEWER'

    ROLE_CHOICES = [
        (ROLE_OWNER, 'Owner'),
        (ROLE_ADMIN, 'Admin'),
        (ROLE_ANALYST, 'Analyst'),
        (ROLE_OPERATOR, 'Operator'),
        (ROLE_VIEWER, 'Viewer'),
    ]

    email = models.EmailField(max_length=320, unique=True)
    phone = models.CharField(max_length=32, null=True, blank=True)
    password_hash = models.CharField(max_length=255, null=True, blank=True)
    display_name = models.CharField(max_length=200, null=True, blank=True)
    
    # AUTH-001 & AUTH-002 fields
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_PENDING)
    role = models.CharField(max_length=32, choices=ROLE_CHOICES, default=ROLE_OWNER)

    is_email_verified = models.BooleanField(default=False)
    email_verification_code = models.CharField(max_length=64, null=True, blank=True)
    email_verification_expires_at = models.DateTimeField(null=True, blank=True)

    # AUTH-003 fields
    password_reset_code = models.CharField(max_length=64, null=True, blank=True)
    password_reset_expires_at = models.DateTimeField(null=True, blank=True)

    failed_login_attempts = models.IntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'users'

    def __str__(self):
        return self.email


class RefreshToken(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='refresh_tokens')
    token = models.CharField(max_length=255, unique=True)
    is_revoked = models.BooleanField(default=False)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'refresh_tokens'

    def __str__(self):
        return f"RefreshToken({self.user.email}, revoked={self.is_revoked})"


class Workspace(models.Model):
    name = models.CharField(max_length=200)
    slug = models.CharField(max_length=80, unique=True, null=True, blank=True)
    owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, db_column='owner_user_id')
    gemini_api_key = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'workspaces'

    def __str__(self):
        return self.name


class WorkspaceMember(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=32, default='MEMBER')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'workspace_members'
        unique_together = ('workspace', 'user')
