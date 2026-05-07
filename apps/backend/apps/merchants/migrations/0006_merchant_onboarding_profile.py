from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('merchants', '0005_merchant_demo_employee'),
    ]

    operations = [
        migrations.AddField(
            model_name='merchant',
            name='address',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='merchant',
            name='business_sector',
            field=models.CharField(blank=True, default='', max_length=120),
        ),
        migrations.AddField(
            model_name='merchant',
            name='tagline',
            field=models.CharField(blank=True, default='', max_length=180),
        ),
        migrations.AddField(
            model_name='merchant',
            name='short_bio',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='merchant',
            name='payment_method',
            field=models.CharField(blank=True, default='', max_length=80),
        ),
        migrations.AddField(
            model_name='merchant',
            name='onboarding_completed',
            field=models.BooleanField(default=False),
        ),
    ]
