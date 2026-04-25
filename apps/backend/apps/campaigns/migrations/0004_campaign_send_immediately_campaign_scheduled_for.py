from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('campaigns', '0003_campaign_cta_label_campaign_landing_headline_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='campaign',
            name='send_immediately',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='campaign',
            name='scheduled_for',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
