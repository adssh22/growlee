from django.db import migrations, models
import django.db.models.deletion


def create_default_subscriptions(apps, schema_editor):
    Merchant = apps.get_model('merchants', 'Merchant')
    Subscription = apps.get_model('merchants', 'Subscription')
    subscriptions = []
    for merchant in Merchant.objects.all().only('id', 'is_active', 'billing_payment_type'):
        if Subscription.objects.filter(merchant_id=merchant.id).exists():
            continue
        provider = 'direct' if merchant.billing_payment_type == 'direct' else 'manual'
        status = 'active' if merchant.is_active else 'suspended'
        subscriptions.append(Subscription(
            merchant_id=merchant.id,
            plan='starter',
            status=status,
            provider=provider,
        ))
    if subscriptions:
        Subscription.objects.bulk_create(subscriptions)


def delete_default_subscriptions(apps, schema_editor):
    Subscription = apps.get_model('merchants', 'Subscription')
    Subscription.objects.filter(provider__in=['manual', 'direct'], provider_customer_id='', provider_subscription_id='').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('merchants', '0009_merchant_contact_design_flyer_offer'),
    ]

    operations = [
        migrations.CreateModel(
            name='Subscription',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('plan', models.CharField(choices=[('starter', 'Starter'), ('pro', 'Pro'), ('premium', 'Premium'), ('custom', 'Custom')], default='starter', max_length=20)),
                ('status', models.CharField(choices=[('trialing', 'Trialing'), ('active', 'Active'), ('past_due', 'Past due'), ('canceled', 'Canceled'), ('suspended', 'Suspended')], default='active', max_length=20)),
                ('provider', models.CharField(choices=[('manual', 'Manual'), ('stripe', 'Stripe'), ('direct', 'Direct')], default='manual', max_length=20)),
                ('provider_customer_id', models.CharField(blank=True, default='', max_length=255)),
                ('provider_subscription_id', models.CharField(blank=True, default='', max_length=255)),
                ('current_period_start', models.DateTimeField(blank=True, null=True)),
                ('current_period_end', models.DateTimeField(blank=True, null=True)),
                ('trial_ends_at', models.DateTimeField(blank=True, null=True)),
                ('canceled_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('merchant', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='subscription', to='merchants.merchant')),
            ],
            options={
                'ordering': ['merchant__name'],
            },
        ),
        migrations.AddIndex(
            model_name='subscription',
            index=models.Index(fields=['status'], name='merchants_s_status_51b2ff_idx'),
        ),
        migrations.AddIndex(
            model_name='subscription',
            index=models.Index(fields=['provider'], name='merchants_s_provide_207b29_idx'),
        ),
        migrations.AddIndex(
            model_name='subscription',
            index=models.Index(fields=['provider_customer_id'], name='merchants_s_provide_445d0b_idx'),
        ),
        migrations.AddIndex(
            model_name='subscription',
            index=models.Index(fields=['provider_subscription_id'], name='merchants_s_provide_8a51c7_idx'),
        ),
        migrations.RunPython(create_default_subscriptions, delete_default_subscriptions),
    ]
