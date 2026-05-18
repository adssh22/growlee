from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import models


def default_employee_pin_hash():
    return make_password('123456')


class Merchant(models.Model):
    FONT_CHOICES = [
        ('inter', 'Inter'),
        ('poppins', 'Poppins'),
        ('manrope', 'Manrope'),
        ('dm-sans', 'DM Sans'),
    ]
    FLYER_STYLE_CHOICES = [
        ('basic', 'Basique'),
        ('premium', 'Premium'),
        ('bold', 'Impact'),
    ]
    FLYER_OFFER_CHOICES = [
        ('1000_80', '1000 flyers · 80€'),
        ('5000_290', '5000 flyers · 290€'),
        ('custom', 'Volume personnalisé'),
    ]

    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    address = models.CharField(max_length=255, blank=True, default='')
    business_sector = models.CharField(max_length=120, blank=True, default='')
    contact_email = models.EmailField(blank=True, default='')
    contact_phone = models.CharField(max_length=40, blank=True, default='')
    tagline = models.CharField(max_length=180, blank=True, default='')
    short_bio = models.TextField(blank=True, default='')
    payment_method = models.CharField(max_length=80, blank=True, default='')
    billing_payment_type = models.CharField(max_length=20, blank=True, default='')
    billing_payment_reference = models.CharField(max_length=120, blank=True, default='')
    flyer_style = models.CharField(max_length=40, choices=FLYER_STYLE_CHOICES, blank=True, default='')
    flyer_offer = models.CharField(max_length=40, choices=FLYER_OFFER_CHOICES, blank=True, default='1000_80')
    flyer_visual_approved = models.BooleanField(default=False)
    flyer_order_status = models.CharField(max_length=40, blank=True, default='pending')
    onboarding_fee_paid = models.BooleanField(default=False)
    logo = models.ImageField(upload_to='merchants/logos/', blank=True, null=True)
    inspiration_image = models.ImageField(upload_to='merchants/inspiration/', blank=True, null=True)
    logo_url = models.URLField(blank=True, null=True)
    design_theme = models.CharField(max_length=120, blank=True, default='')
    primary_color = models.CharField(max_length=20, default='#111827')
    accent_color = models.CharField(max_length=20, default='#22c55e')
    surface_color = models.CharField(max_length=20, default='#ffffff')
    text_color = models.CharField(max_length=20, default='#1f2937')
    heading_font = models.CharField(max_length=40, choices=FONT_CHOICES, default='inter')
    body_font = models.CharField(max_length=40, choices=FONT_CHOICES, default='inter')
    google_review_url = models.URLField(blank=True, null=True)
    public_journey_tested = models.BooleanField(default=False)
    employee_pin_hash = models.CharField(max_length=128, default=default_employee_pin_hash)
    is_demo = models.BooleanField(default=False)
    onboarding_completed = models.BooleanField(default=False)
    demo_expires_at = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    deleted_at = models.DateTimeField(blank=True, null=True, db_index=True)
    deleted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, blank=True, null=True, related_name='archived_merchants')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    @property
    def is_archived(self):
        return self.deleted_at is not None

    def set_employee_pin(self, raw_pin):
        self.employee_pin_hash = make_password(raw_pin)

    def check_employee_pin(self, raw_pin):
        return bool(raw_pin and self.employee_pin_hash and check_password(raw_pin, self.employee_pin_hash))

    def __str__(self):
        return self.name


class Subscription(models.Model):
    PLAN_STARTER = 'starter'
    PLAN_PRO = 'pro'
    PLAN_PREMIUM = 'premium'
    PLAN_CUSTOM = 'custom'
    PLAN_CHOICES = [
        (PLAN_STARTER, 'Starter'),
        (PLAN_PRO, 'Pro'),
        (PLAN_PREMIUM, 'Premium'),
        (PLAN_CUSTOM, 'Custom'),
    ]

    STATUS_TRIALING = 'trialing'
    STATUS_ACTIVE = 'active'
    STATUS_PAST_DUE = 'past_due'
    STATUS_CANCELED = 'canceled'
    STATUS_SUSPENDED = 'suspended'
    STATUS_CHOICES = [
        (STATUS_TRIALING, 'Trialing'),
        (STATUS_ACTIVE, 'Active'),
        (STATUS_PAST_DUE, 'Past due'),
        (STATUS_CANCELED, 'Canceled'),
        (STATUS_SUSPENDED, 'Suspended'),
    ]
    UNLOCKED_STATUSES = {STATUS_TRIALING, STATUS_ACTIVE}

    PROVIDER_MANUAL = 'manual'
    PROVIDER_STRIPE = 'stripe'
    PROVIDER_DIRECT = 'direct'
    PROVIDER_CHOICES = [
        (PROVIDER_MANUAL, 'Manual'),
        (PROVIDER_STRIPE, 'Stripe'),
        (PROVIDER_DIRECT, 'Direct'),
    ]

    merchant = models.OneToOneField(Merchant, on_delete=models.CASCADE, related_name='subscription')
    plan = models.CharField(max_length=20, choices=PLAN_CHOICES, default=PLAN_STARTER)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, default=PROVIDER_MANUAL)
    provider_customer_id = models.CharField(max_length=255, blank=True, default='')
    provider_subscription_id = models.CharField(max_length=255, blank=True, default='')
    current_period_start = models.DateTimeField(blank=True, null=True)
    current_period_end = models.DateTimeField(blank=True, null=True)
    trial_ends_at = models.DateTimeField(blank=True, null=True)
    canceled_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['merchant__name']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['provider']),
            models.Index(fields=['provider_customer_id']),
            models.Index(fields=['provider_subscription_id']),
        ]

    def __str__(self):
        return f'{self.merchant} · {self.plan} · {self.status}'

    @property
    def unlocks_paid_features(self):
        return self.status in self.UNLOCKED_STATUSES
