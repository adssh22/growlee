from django.db import models


class Merchant(models.Model):
    FONT_CHOICES = [
        ('inter', 'Inter'),
        ('poppins', 'Poppins'),
        ('manrope', 'Manrope'),
        ('dm-sans', 'DM Sans'),
    ]

    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    address = models.CharField(max_length=255, blank=True, default='')
    business_sector = models.CharField(max_length=120, blank=True, default='')
    tagline = models.CharField(max_length=180, blank=True, default='')
    short_bio = models.TextField(blank=True, default='')
    payment_method = models.CharField(max_length=80, blank=True, default='')
    logo = models.ImageField(upload_to='merchants/logos/', blank=True, null=True)
    logo_url = models.URLField(blank=True, null=True)
    primary_color = models.CharField(max_length=20, default='#111827')
    accent_color = models.CharField(max_length=20, default='#22c55e')
    surface_color = models.CharField(max_length=20, default='#ffffff')
    text_color = models.CharField(max_length=20, default='#1f2937')
    heading_font = models.CharField(max_length=40, choices=FONT_CHOICES, default='inter')
    body_font = models.CharField(max_length=40, choices=FONT_CHOICES, default='inter')
    google_review_url = models.URLField(blank=True, null=True)
    employee_pin = models.CharField(max_length=12, default='1234')
    is_demo = models.BooleanField(default=False)
    onboarding_completed = models.BooleanField(default=False)
    demo_expires_at = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name
