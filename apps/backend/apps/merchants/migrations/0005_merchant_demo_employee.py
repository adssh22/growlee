# Generated manually for Growlee MVP employee/demo access

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('merchants', '0004_merchant_google_review_url'),
    ]

    operations = [
        migrations.AddField(
            model_name='merchant',
            name='employee_pin',
            field=models.CharField(default='1234', max_length=12),
        ),
        migrations.AddField(
            model_name='merchant',
            name='is_demo',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='merchant',
            name='demo_expires_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
