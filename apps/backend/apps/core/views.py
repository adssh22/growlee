import csv
import io
import base64
import mimetypes
from datetime import datetime, timedelta
from types import SimpleNamespace

from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth import login, logout
from django.core.mail import send_mail
from django.utils.html import escape
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import slugify
from django.db.models import Q
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from django.conf import settings
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

import qrcode
import qrcode.image.svg

from apps.accounts.models import MerchantMembership, StaffMFA
from apps.campaigns.models import Campaign, EntryPoint, WheelSegment
from apps.core.forms import CampaignForm, EntryPointForm, MerchantForm, MerchantReviewForm, MerchantSignupForm, RewardForm, StaffMerchantCreateForm
from apps.core.totp import generate_secret, provisioning_uri, verify_totp
from apps.core.utils import build_qr_svg, generate_qr_data_uri
from apps.core.security import rate_limit
from apps.customers.forms import ClaimRewardForm
from apps.customers.models import Customer, GameSession, WalletPass
from apps.customers.services import claim_reward, reward_claim_url, send_reward_notifications
from apps.customers.wallet import build_wallet_payload, issue_wallet_pass_placeholder, wallet_config_status
from apps.merchants.models import Merchant
from apps.rewards.models import Reward


def _current_merchant(request):
    membership = MerchantMembership.objects.select_related('merchant').filter(user=request.user).first()
    return membership.merchant if membership else None


def home(request):
    return render(request, 'public/home.html', {'seo_base_url': settings.APP_BASE_URL})


@rate_limit('contact_page', limit=10, limit_setting='RATELIMIT_CONTACT_ATTEMPTS', window=3600)
def contact_page(request):
    sent = False
    if request.method == 'POST':
        name = (request.POST.get('name') or '').strip()
        email = (request.POST.get('email') or '').strip()
        need = (request.POST.get('need') or '').strip()
        message = (request.POST.get('message') or '').strip()
        if name and email and message:
            body = f"Nom / commerce : {name}\nEmail : {email}\nBesoin : {need}\n\nMessage :\n{message}"
            send_mail(
                subject=f'Demande Growlee — {need or "Contact"}',
                message=body,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None) or 'contact@growlee.fr',
                recipient_list=['contact@growlee.fr'],
                fail_silently=True,
            )
            sent = True
    return render(request, 'public/contact.html', {
        'title': 'Contact',
        'description': 'Contactez Growlee pour une démo, un lancement commerce, un partenariat ou une offre multi-sites.',
        'canonical_url': 'https://growlee.fr/contact/',
        'sent': sent,
    })


@csrf_exempt
@rate_limit('api_contact', limit=10, limit_setting='RATELIMIT_CONTACT_ATTEMPTS', window=3600)
def api_contact(request):
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'method_not_allowed'}, status=405)
    name = (request.POST.get('name') or request.POST.get('full_name') or '').strip()
    email = (request.POST.get('email') or '').strip()
    phone = (request.POST.get('phone') or '').strip()
    need = (request.POST.get('need') or '').strip()
    message = (request.POST.get('message') or '').strip()
    rgpd = request.POST.get('rgpd') in {'on', 'true', '1', 'yes'}
    if not name or '@' not in email or len(message) < 10 or not rgpd:
        return JsonResponse({'ok': False, 'error': 'invalid_fields'}, status=400)
    body = f"Nom complet : {name}\nEmail : {email}\nTéléphone : {phone or '-'}\nType de demande : {need or '-'}\nRGPD : accepté\n\nMessage :\n{message}"
    send_mail(
        subject=f'Demande Growlee — {need or "Contact"}',
        message=body,
        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None) or 'contact@growlee.fr',
        recipient_list=['contact@growlee.fr'],
        fail_silently=True,
    )
    return JsonResponse({'ok': True})


def partners_page(request):
    return render(request, 'public/partners.html', {
        'title': "Devenez apporteur d'affaires Growlee",
        'description': "Prospectez les commerçants locaux, posez les rendez-vous. On s'occupe du reste. Vous touchez 30€/mois par client actif pendant 12 mois.",
        'canonical_url': 'https://growlee.fr/apporteurs/',
        'plain_hero': True,
    })


def demo_page(request):
    return render(request, 'public/demo.html', {
        'title': 'Démo interactive Growlee',
        'description': 'Un aperçu cliquable du parcours Growlee : scan QR, jeu, gain, avis Google, wallet et retour client.',
        'canonical_url': 'https://growlee.fr/demo/',
        'plain_hero': True,
    })


def resources_page(request):
    return render(request, 'public/resources.html', {
        'title': 'Ressources',
        'description': 'Guides Growlee pour lancer un QR en boutique, collecter plus d’avis et fidéliser les clients.',
    })


def legal_page(request, page):
    pages = {
        'mentions-legales': {
            'title': 'Mentions légales',
            'description': 'Informations légales de Growlee.',
            'sections': [
                {
                    'title': 'Éditeur du site',
                    'paragraphs': [
                        'Le site growlee.fr est édité par la société GROWLEE, [forme juridique à compléter], dont le siège social est situé à [adresse à compléter], immatriculée au Registre du Commerce et des Sociétés sous le numéro [SIREN à compléter].',
                        'Email : <a href="mailto:contact@growlee.fr">contact@growlee.fr</a>',
                        'Site web : <a href="https://growlee.fr">https://growlee.fr</a>',
                    ],
                },
                {'title': 'Directeur de la publication', 'paragraphs': ['[Nom du dirigeant à compléter]']},
                {'title': 'Hébergement', 'paragraphs': ["[Nom de l'hébergeur à compléter], [adresse de l'hébergeur à compléter]"]},
                {
                    'title': 'Propriété intellectuelle',
                    'paragraphs': ["L'ensemble du contenu du site growlee.fr (textes, images, logotypes, vidéos, éléments graphiques) est la propriété exclusive de GROWLEE ou de ses partenaires et est protégé par le droit d'auteur. Toute reproduction, représentation, modification, publication ou adaptation de tout ou partie des éléments du site, quel que soit le moyen ou le procédé utilisé, est interdite sans autorisation préalable écrite de GROWLEE."],
                },
                {
                    'title': 'Limitation de responsabilité',
                    'paragraphs': ["GROWLEE ne peut être tenu responsable des dommages directs ou indirects causés au matériel de l'utilisateur, lors de l'accès au site growlee.fr. GROWLEE décline toute responsabilité quant aux éventuels virus pouvant infecter l'ordinateur ou tout matériel informatique de l'utilisateur suite à une utilisation ou un accès au site."],
                },
            ],
        },
        'cgv': {
            'title': 'Conditions Générales de Vente',
            'description': 'Conditions Générales de Vente de la solution Growlee.',
            'sections': [
                {'title': 'Article 1 — Objet', 'paragraphs': ["Les présentes Conditions Générales de Vente (CGV) s'appliquent à toutes les souscriptions à la solution Growlee effectuées via le site growlee.fr ou tout autre canal de vente de la société GROWLEE."]},
                {
                    'title': 'Article 2 — Offre et tarification',
                    'paragraphs': ["L'offre Growlee comprend :"],
                    'items': [
                        "Des frais d'installation uniques de 80€ TTC, non remboursables, payables à la souscription",
                        "Un premier mois d'accès gratuit (mois d'activation)",
                        'Un abonnement mensuel de 90€ TTC (75€ HT) à compter du deuxième mois, prélevé automatiquement',
                    ],
                },
                {'title': 'Offre multi-sites', 'paragraphs': ["L'offre multi-sites fait l'objet d'un devis personnalisé disponible sur demande à <a href=\"mailto:contact@growlee.fr\">contact@growlee.fr</a>."]},
                {'title': 'Article 3 — Durée et résiliation', 'paragraphs': ["L'abonnement est sans engagement de durée minimale. Le client peut résilier à tout moment par notification écrite à <a href=\"mailto:contact@growlee.fr\">contact@growlee.fr</a>. La résiliation prend effet à l'issue de la période mensuelle en cours."]},
                {'title': 'Article 4 — Paiement', 'paragraphs': ["Le paiement des frais d'installation est effectué en ligne à la souscription. L'abonnement mensuel est prélevé automatiquement. En cas d'échec de prélèvement, GROWLEE accordera un délai de 7 jours pour régularisation."]},
                {'title': 'Article 5 — Rétractation', 'paragraphs': ["Conformément à l'article L221-28 du Code de la consommation, le droit de rétractation ne s'applique pas aux services pleinement exécutés avant la fin du délai de rétractation avec l'accord préalable exprès du consommateur. Les frais d'installation étant liés à des prestations immédiates, ils sont non remboursables."]},
                {'title': 'Article 6 — Droit applicable', 'paragraphs': ["Les présentes CGV sont soumises au droit français. Tout litige sera soumis aux tribunaux compétents du ressort du siège social de GROWLEE.", '<em>Dernière mise à jour : [date à compléter]</em>']},
            ],
        },
        'confidentialite': {
            'title': 'Politique de confidentialité',
            'description': 'Politique de confidentialité Growlee.',
            'sections': [
                {'title': '1. Responsable du traitement', 'paragraphs': ['GROWLEE, [adresse à compléter] — <a href="mailto:contact@growlee.fr">contact@growlee.fr</a>']},
                {
                    'title': '2. Données collectées',
                    'paragraphs': ["Dans le cadre de l'utilisation du site et de la solution Growlee, nous collectons les données suivantes :"],
                    'items': [
                        "Données d'identification : nom, prénom, raison sociale",
                        'Données de contact : email, téléphone, adresse',
                        'Données de paiement : traitées exclusivement par notre prestataire de paiement sécurisé (Stripe)',
                        "Données d'usage : connexions, activité sur la plateforme",
                    ],
                },
                {
                    'title': '3. Finalités du traitement',
                    'paragraphs': ['Les données sont collectées pour :'],
                    'items': [
                        'La fourniture et la gestion du service Growlee',
                        'La facturation et le suivi comptable',
                        "L'envoi de communications liées au service",
                        "L'amélioration de la plateforme",
                    ],
                },
                {'title': '4. Base légale', 'paragraphs': ["Le traitement est fondé sur l'exécution du contrat (art. 6.1.b RGPD) et, pour les communications marketing, sur le consentement (art. 6.1.a RGPD)."]},
                {'title': '5. Durée de conservation', 'paragraphs': ["Les données sont conservées pendant la durée du contrat et jusqu'à 3 ans après sa fin pour les données commerciales, et 10 ans pour les données comptables."]},
                {'title': '6. Vos droits', 'paragraphs': ["Conformément au RGPD, vous disposez d'un droit d'accès, de rectification, d'effacement, de portabilité et d'opposition. Pour exercer ces droits : <a href=\"mailto:contact@growlee.fr\">contact@growlee.fr</a>"]},
                {'title': '7. Cookies', 'paragraphs': ["Le site utilise des cookies techniques nécessaires au fonctionnement. Aucun cookie de tracking publicitaire tiers n'est utilisé."]},
                {'title': '8. Modifications', 'paragraphs': ['GROWLEE se réserve le droit de modifier cette politique. La version en vigueur est celle publiée sur cette page.', '<em>Dernière mise à jour : [date à compléter]</em>']},
            ],
        },
    }
    if page not in pages:
        raise Http404('Page légale introuvable')
    data = pages[page]
    return render(request, 'public/legal.html', {
        'title': data['title'],
        'description': data['description'],
        'legal_sections': data['sections'],
        'canonical_url': f'https://growlee.fr/{page}/',
        'robots_meta': 'noindex, follow',
        'plain_hero': True,
    })


def robots_txt(request):
    body = 'User-agent: *\nAllow: /\nDisallow: /login/\nDisallow: /signup/\nDisallow: /dashboard/\nDisallow: /admin/\n\nSitemap: https://growlee.fr/sitemap.xml\n'
    return HttpResponse(body, content_type='text/plain; charset=utf-8')


def sitemap_xml(request):
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n <url>\n <loc>https://growlee.fr/</loc>\n <changefreq>weekly</changefreq>\n <priority>1.0</priority>\n </url>\n <url>\n <loc>https://growlee.fr/contact/</loc>\n <changefreq>monthly</changefreq>\n <priority>0.8</priority>\n </url>\n <url>\n <loc>https://growlee.fr/apporteurs/</loc>\n <changefreq>monthly</changefreq>\n <priority>0.8</priority>\n </url>\n <url>\n <loc>https://growlee.fr/mentions-legales/</loc>\n <changefreq>yearly</changefreq>\n <priority>0.3</priority>\n </url>\n <url>\n <loc>https://growlee.fr/cgv/</loc>\n <changefreq>yearly</changefreq>\n <priority>0.3</priority>\n </url>\n <url>\n <loc>https://growlee.fr/confidentialite/</loc>\n <changefreq>yearly</changefreq>\n <priority>0.3</priority>\n </url>\n</urlset>\n'
    return HttpResponse(xml, content_type='application/xml; charset=utf-8')


def _first_membership(user):
    return MerchantMembership.objects.select_related('merchant').filter(user=user).first()


def _merchant_is_unlocked(merchant):
    if merchant and merchant.is_demo and merchant.demo_expires_at and merchant.demo_expires_at < timezone.now():
        return False
    return bool(merchant and merchant.is_active)


def _merchant_logo_for_svg(merchant):
    """Return an embeddable logo URI for QR SVGs.

    Browsers/printers often block nested external images when an SVG is opened
    directly or downloaded. Embedding uploaded logos as data URIs makes the QR
    self-contained and keeps the branding visible everywhere.
    """
    if not merchant:
        return None
    if merchant.logo and merchant.logo.name:
        try:
            with merchant.logo.open('rb') as logo_file:
                raw = logo_file.read()
            content_type = mimetypes.guess_type(merchant.logo.name)[0] or 'image/png'
            return f"data:{content_type};base64,{base64.b64encode(raw).decode('ascii')}"
        except Exception:
            return merchant.logo.url
    return merchant.logo_url or None


def _pricing_plans():
    return [
        {
            'key': 'all_inclusive',
            'name': 'Tout inclus',
            'price': '90€ TTC / mois',
            'tagline': 'Une offre simple pour lancer Growlee dans votre restaurant.',
            'features': ['Parcours QR mobile premium', 'Jeu cadeau', 'Avis Google + feedback privé', 'Wallet fidélité', 'Notifications push Apple Wallet', 'Campagnes SMS & Email', 'Personnalisation logo/couleurs', 'Clients cloisonnés par commerce'],
            'payment_link': settings.GROWLEE_PAYMENT_LINK_PRO,
            'highlight': True,
            'cta': 'Acheter maintenant',
        },
        {
            'key': 'multi_restaurant',
            'name': 'Multi-restaurants',
            'price': 'Sur devis',
            'tagline': 'Pour les groupes, franchises ou plusieurs établissements.',
            'features': ['Plusieurs restaurants', 'Gestion centralisée', 'Offres et modules par établissement', 'Accompagnement au lancement', 'Tarif adapté au volume'],
            'payment_link': '',
            'contact': True,
            'cta': 'Contactez-nous',
        },
    ]


def _employee_mode_block_response(request):
    allowed_paths = {'/admin/employee/', '/admin/employee/exit/', '/logout/'}
    if request.session.get('growlee_employee_mode') and request.path not in allowed_paths:
        return redirect('employee-mode')
    return None


def _admin_access_block_response(request, merchant=None):
    employee_block = _employee_mode_block_response(request)
    if employee_block is not None:
        return employee_block
    if request.user.is_superuser:
        return redirect('staff-merchants')
    membership = _first_membership(request.user)
    merchant = merchant or (membership.merchant if membership else None)
    if merchant is None:
        messages.error(request, 'Aucun commerce n’est rattaché à ce compte.')
        return redirect('logout')
    onboarding_allowed = {
        '/admin/account/',
        '/admin/onboarding/',
        '/admin/checkout/',
        '/logout/',
    }
    if not _merchant_is_unlocked(merchant) and request.path not in onboarding_allowed:
        return render(request, 'admin/pending_payment.html', {'merchant': merchant, 'pricing_plans': _pricing_plans()})
    if request.path not in onboarding_allowed:
        billing_validated = merchant.is_active and merchant.onboarding_fee_paid
        if not billing_validated:
            if not merchant.onboarding_completed:
                messages.info(request, 'Complétez l’onboarding commerçant pour personnaliser votre interface Growlee.')
                return redirect('merchant-account')
            if not merchant.flyer_style or not merchant.flyer_visual_approved:
                messages.info(request, 'Validez votre flyer pour débloquer votre dashboard et préparer le paiement.')
                return redirect('merchant-account')
        dashboard_preview_allowed = {'/admin/'}
        if not billing_validated and request.path not in dashboard_preview_allowed:
            messages.info(request, 'Votre dashboard et votre QR sont prêts. Finalisez le paiement onboarding pour débloquer toute l’application.')
            return redirect('admin-dashboard')
    return None


def merchant_unlocked_required(view_func):
    def wrapper(request, *args, **kwargs):
        blocked = _admin_access_block_response(request)
        if blocked is not None:
            return blocked
        return view_func(request, *args, **kwargs)
    return wrapper



def _unique_merchant_slug(name):
    base = slugify(name) or 'commerce'
    slug = base[:48]
    counter = 2
    while Merchant.objects.filter(slug=slug).exists():
        suffix = f'-{counter}'
        slug = f"{base[:48-len(suffix)]}{suffix}"
        counter += 1
    return slug


@rate_limit('signup', limit=5, limit_setting='RATELIMIT_SIGNUP_ATTEMPTS', window=3600)
def signup_view(request):
    if request.user.is_authenticated:
        return redirect('admin-dashboard')
    form = MerchantSignupForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        merchant = Merchant.objects.create(
            name=form.cleaned_data['business_name'],
            slug=_unique_merchant_slug(form.cleaned_data['business_name']),
            primary_color='#4e3db7',
            accent_color='#3f9d87',
            is_active=False,
        )
        MerchantMembership.objects.create(user=user, merchant=merchant, role='owner')
        campaign, _, _ = _ensure_default_growlee_setup(merchant)
        campaign.is_active = False
        campaign.review_enabled = False
        campaign.wallet_enabled = False
        campaign.save(update_fields=['is_active', 'review_enabled', 'wallet_enabled'])
        login(request, user)
        messages.success(request, 'Compte créé. Votre espace sera activé après validation du paiement.')
        return redirect('admin-dashboard')
    return render(request, 'admin/signup.html', {'form': form})

@rate_limit('login', limit=8, limit_setting='RATELIMIT_LOGIN_ATTEMPTS', window=900)
def login_view(request):
    if request.user.is_authenticated:
        if request.user.is_superuser:
            return redirect('staff-merchants')
        return redirect('admin-dashboard')
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        login(request, form.get_user())
        next_url = request.GET.get('next') or ''
        if form.get_user().is_superuser and (next_url in {'', '/admin/'}):
            return redirect('staff-merchants')
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)
        return redirect('admin-dashboard')
    return render(request, 'admin/login.html', {'form': form})


def logout_view(request):
    logout(request)
    return redirect('home')


def _control_access_granted(request):
    return bool(request.session.get('growlee_control_2fa_ok'))


def _is_superuser(user):
    return bool(user.is_authenticated and user.is_active and user.is_superuser)


superuser_required = user_passes_test(_is_superuser, login_url='/login/')


def _staff_mfa_for_user(user):
    mfa, _ = StaffMFA.objects.get_or_create(user=user, defaults={'secret': generate_secret()})
    if not mfa.secret:
        mfa.secret = generate_secret()
        mfa.save(update_fields=['secret', 'updated_at'])
    return mfa


def _staff_mfa_qr_context(user, mfa=None):
    mfa = mfa or _staff_mfa_for_user(user)
    uri = provisioning_uri(mfa.secret, user.username)
    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage)
    buffer = io.BytesIO()
    img.save(buffer)
    return {
        'mfa': mfa,
        'qr_svg': buffer.getvalue().decode('utf-8'),
        'secret': mfa.secret,
        'otpauth_uri': uri,
    }


@superuser_required
def staff_control_mfa_setup(request):
    mfa = _staff_mfa_for_user(request.user)
    if mfa.enabled:
        messages.info(request, 'Ta 2FA est déjà activée. La réinitialisation doit être faite par un autre super utilisateur.')
        return redirect('staff-merchants' if _control_access_granted(request) else 'staff-control-verify')

    error = None

    if request.method == 'POST':
        if verify_totp(mfa.secret, request.POST.get('totp_code')):
            mfa.enabled = True
            mfa.save(update_fields=['enabled', 'updated_at'])
            request.session['growlee_control_2fa_ok'] = True
            request.session.set_expiry(60 * 60 * 4)
            messages.success(request, '2FA téléphone activée.')
            return redirect('staff-merchants')
        error = 'Code 2FA invalide. Vérifie l’heure du téléphone et réessaie.'

    context = _staff_mfa_qr_context(request.user, mfa)
    context.update({
        'error': error,
    })
    return render(request, 'admin/staff_control_mfa_setup.html', context)


@superuser_required
def staff_control_verify(request):
    if _control_access_granted(request):
        return redirect('staff-merchants')

    mfa = _staff_mfa_for_user(request.user)
    if not mfa.enabled:
        return redirect('staff-merchants')

    error = None
    if request.method == 'POST':
        if verify_totp(mfa.secret, request.POST.get('totp_code')):
            request.session['growlee_control_2fa_ok'] = True
            request.session.set_expiry(60 * 60 * 4)
            next_url = request.GET.get('next') or ''
            if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
                return redirect(next_url)
            return redirect('staff-merchants')
        error = 'Code 2FA invalide.'

    return render(request, 'admin/staff_control_verify.html', {'error': error})


def _get_active_campaign_for_merchant(merchant):
    if merchant is None:
        return None
    # Le parcours client suit la campagne courante du commerçant.
    # Si la dernière campagne / le module Jeu est désactivé côté admin,
    # on ne retombe pas sur une ancienne campagne active : le parcours est coupé aussi.
    campaign = Campaign.objects.filter(merchant=merchant).order_by('-created_at', '-id').first()
    return campaign if campaign and campaign.is_active else None


def _merchant_context_for_user(user):
    membership = _first_membership(user)
    merchant = membership.merchant if membership else None
    campaigns = Campaign.objects.filter(merchant=merchant).order_by('-created_at', '-id') if merchant else Campaign.objects.none()
    # L'admin doit refléter la campagne que l'utilisateur vient de modifier,
    # même si elle est désactivée. Sinon le dashboard retombe sur une ancienne
    # campagne active et les toggles semblent ne pas se mettre à jour.
    campaign = campaigns.first()
    entry_points = EntryPoint.objects.filter(merchant=merchant) if merchant else []
    primary_entry = entry_points.order_by('created_at', 'id').first() if merchant else None
    rewards = Reward.objects.filter(merchant=merchant) if merchant else []
    customers = Customer.objects.filter(merchant=merchant).order_by('-created_at')[:10] if merchant else []
    distributed = GameSession.objects.filter(campaign__merchant=merchant).count() if merchant else 0
    redeemed = GameSession.objects.filter(campaign__merchant=merchant, redeemed=True).count() if merchant else 0
    gains_won = GameSession.objects.filter(campaign__merchant=merchant, is_winner=True).count() if merchant else 0
    gains_waiting = GameSession.objects.filter(campaign__merchant=merchant, is_winner=True, redeemed=False).count() if merchant else 0
    now = timezone.now()
    active_campaigns = campaigns.filter(is_active=True).filter(
        Q(send_immediately=True) | Q(scheduled_for__isnull=True) | Q(scheduled_for__lte=now)
    )
    scheduled_campaigns = campaigns.filter(is_active=True, send_immediately=False, scheduled_for__gt=now)
    stats = {
        'scans': distributed,
        'contacts': Customer.objects.filter(merchant=merchant).count() if merchant else 0,
        'wallets': redeemed,
        'return_rate': f"{int((redeemed / distributed) * 100) if distributed else 0}%",
        'distributed': distributed,
        'redeemed': redeemed,
        'gains_won': gains_won,
        'gains_waiting': gains_waiting,
        'review_clicks': 0,
        'review_target': 20,
        'campaigns_live': active_campaigns.count(),
        'campaigns_scheduled': scheduled_campaigns.count(),
    }
    game_active = bool(campaign and campaign.is_active)
    review_active = bool(campaign and campaign.review_enabled)
    wallet_active = bool(campaign and campaign.wallet_enabled)
    return {
        'merchant': merchant,
        'campaign': campaign,
        'campaigns': campaigns,
        'active_campaigns': active_campaigns[:5],
        'scheduled_campaigns': scheduled_campaigns[:5],
        'entry_points': entry_points,
        'primary_entry': primary_entry,
        'rewards': rewards,
        'customers': customers,
        'stats': stats,
        'game_active': game_active,
        'review_active': review_active,
        'wallet_active': wallet_active,
        'active_modules_count': int(game_active) + int(review_active) + int(wallet_active),
    }


@login_required
def admin_dashboard(request):
    if request.user.is_superuser:
        return redirect('staff-merchants')
    context = _merchant_context_for_user(request.user)
    if context['merchant'] is None:
        if request.user.is_staff:
            return redirect('staff-merchants')
        messages.error(request, 'Aucun commerce n’est rattaché à ce compte.')
        return redirect('logout')
    blocked = _admin_access_block_response(request, context['merchant'])
    if blocked is not None:
        return blocked
    return render(request, 'admin/dashboard.html', context)


@superuser_required
def staff_merchants(request):
    mfa = _staff_mfa_for_user(request.user)
    if not mfa.enabled:
        return redirect('staff-control-mfa-setup')
    if mfa.enabled and not _control_access_granted(request):
        return redirect(f'/growlee-control/verify/?next={request.path}')

    form = StaffMerchantCreateForm(request.POST or None)
    mfa_error = None
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'reset_staff_mfa':
            target_user = get_object_or_404(User, id=request.POST.get('user_id'), is_active=True, is_superuser=True)
            if target_user.id == request.user.id:
                messages.error(request, 'Impossible de réinitialiser ta propre 2FA. Demande à un autre super utilisateur.')
                return redirect('staff-merchants')
            target_mfa = _staff_mfa_for_user(target_user)
            target_mfa.secret = generate_secret()
            target_mfa.enabled = False
            target_mfa.save(update_fields=['secret', 'enabled', 'updated_at'])
            messages.success(request, f'2FA réinitialisée pour {target_user.username}. Il devra scanner un nouveau QR au prochain accès.')
            return redirect('staff-merchants')
        if action == 'mfa_enable':
            if verify_totp(mfa.secret, request.POST.get('totp_code')):
                mfa.enabled = True
                mfa.save(update_fields=['enabled', 'updated_at'])
                request.session['growlee_control_2fa_ok'] = True
                request.session.set_expiry(60 * 60 * 4)
                messages.success(request, '2FA téléphone activée pour ce compte staff.')
                return redirect('staff-merchants')
            mfa_error = 'Code 2FA invalide. Vérifie l’heure du téléphone et réessaie.'
        if action == 'toggle':
            merchant = get_object_or_404(Merchant, id=request.POST.get('merchant_id'))
            merchant.is_active = not merchant.is_active
            merchant.save(update_fields=['is_active'])
            messages.success(request, f'{merchant.name} est maintenant {"actif" if merchant.is_active else "désactivé"}.')
            return redirect('staff-merchants')
        if action == 'toggle_demo':
            merchant = get_object_or_404(Merchant, id=request.POST.get('merchant_id'))
            merchant.is_demo = not merchant.is_demo
            merchant.demo_expires_at = timezone.now() + timedelta(days=14) if merchant.is_demo else None
            merchant.is_active = True if merchant.is_demo else merchant.is_active
            merchant.save(update_fields=['is_demo', 'demo_expires_at', 'is_active'])
            messages.success(request, f'Accès démo {"activé" if merchant.is_demo else "désactivé"} pour {merchant.name}.')
            return redirect('staff-merchants')
        if action == 'activate_direct_billing':
            merchant = get_object_or_404(Merchant, id=request.POST.get('merchant_id'))
            merchant.is_active = True
            merchant.is_demo = False
            merchant.demo_expires_at = None
            merchant.onboarding_fee_paid = True
            merchant.onboarding_completed = True
            merchant.flyer_visual_approved = True
            merchant.flyer_order_status = 'visual_approved_waiting_payment'
            if not merchant.flyer_style:
                merchant.flyer_style = 'premium'
            merchant.payment_method = 'Facturation directe'
            merchant.billing_payment_type = 'direct'
            merchant.billing_payment_reference = (request.POST.get('billing_reference') or '').strip()[:120] or 'Activation manuelle staff'
            merchant.save(update_fields=['is_active', 'is_demo', 'demo_expires_at', 'onboarding_fee_paid', 'onboarding_completed', 'flyer_visual_approved', 'flyer_order_status', 'flyer_style', 'payment_method', 'billing_payment_type', 'billing_payment_reference'])
            campaign, _, _ = _ensure_default_growlee_setup(merchant)
            campaign.is_active = True
            campaign.review_enabled = True
            campaign.wallet_enabled = True
            campaign.save(update_fields=['is_active', 'review_enabled', 'wallet_enabled'])
            messages.success(request, f'{merchant.name} est activé en facturation directe. Le commerçant peut accéder à son compte sans paiement via le site.')
            return redirect('staff-merchants')
        if action == 'delete_merchant':
            merchant = get_object_or_404(Merchant, id=request.POST.get('merchant_id'))
            confirm = (request.POST.get('confirm_name') or '').strip()
            if confirm != merchant.name:
                messages.error(request, f'Suppression annulée : tape exactement le nom du commerce ({merchant.name}).')
                return redirect('staff-merchants')
            merchant_name = merchant.name
            owner_users = [membership.user for membership in merchant.memberships.select_related('user').all()]
            merchant.delete()
            for user in owner_users:
                if not user.is_staff and not user.merchant_memberships.exists():
                    user.delete()
            messages.success(request, f'Commerce supprimé : {merchant_name}.')
            return redirect('staff-merchants')
        if action == 'module_toggle':
            merchant = get_object_or_404(Merchant, id=request.POST.get('merchant_id'))
            campaign = Campaign.objects.filter(merchant=merchant).order_by('-created_at', '-id').first()
            if campaign is None:
                campaign, _, _ = _ensure_default_growlee_setup(merchant)
                campaign.is_active = False
                campaign.review_enabled = False
                campaign.wallet_enabled = False
                campaign.save(update_fields=['is_active', 'review_enabled', 'wallet_enabled'])
            flag = request.POST.get('flag')
            if flag == 'game':
                campaign.is_active = not campaign.is_active
                campaign.save(update_fields=['is_active'])
            elif flag == 'review':
                campaign.review_enabled = not campaign.review_enabled
                campaign.save(update_fields=['review_enabled'])
            elif flag == 'wallet':
                campaign.wallet_enabled = not campaign.wallet_enabled
                campaign.save(update_fields=['wallet_enabled'])
            messages.success(request, f'Module mis à jour pour {merchant.name}.')
            return redirect('staff-merchants')
        if action == 'create' and form.is_valid():
            with transaction.atomic():
                email = form.cleaned_data['owner_email']
                username = form.cleaned_data['owner_username'] or email
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=form.cleaned_data['owner_password'],
                )
                merchant = Merchant.objects.create(
                    name=form.cleaned_data['merchant_name'],
                    slug=_unique_merchant_slug(form.cleaned_data['merchant_name']),
                    primary_color='#4e3db7',
                    accent_color='#3f9d87',
                    is_active=form.cleaned_data['is_active'],
                    is_demo=form.cleaned_data.get('is_demo') or False,
                    demo_expires_at=(timezone.now() + timedelta(days=form.cleaned_data.get('demo_days') or 14)) if form.cleaned_data.get('is_demo') else None,
                )
                MerchantMembership.objects.create(user=user, merchant=merchant, role='owner')
                _ensure_default_growlee_setup(merchant)
            messages.success(request, f'Commerce créé : {merchant.name}. Propriétaire : {user.username}')
            return redirect('staff-merchants')

    merchants = Merchant.objects.prefetch_related('memberships__user').order_by('-created_at')
    rows = []
    for merchant in merchants:
        campaigns = Campaign.objects.filter(merchant=merchant)
        rows.append({
            'merchant': merchant,
            'owners': [m for m in merchant.memberships.all() if m.role == 'owner'],
            'campaigns_count': campaigns.count(),
            'customers_count': Customer.objects.filter(merchant=merchant).count(),
            'active_campaign': campaigns.order_by('-created_at', '-id').first(),
        })
    mfa_context = _staff_mfa_qr_context(request.user, mfa)
    staff_mfa_users = User.objects.filter(is_active=True, is_superuser=True).order_by('username')
    return render(request, 'admin/staff_merchants.html', {
        'form': form,
        'rows': rows,
        'staff_mfa_users': staff_mfa_users,
        'total_merchants': merchants.count(),
        'active_merchants': merchants.filter(is_active=True).count(),
        'total_users': User.objects.count(),
        'mfa_error': mfa_error,
        **mfa_context,
    })


def _ensure_default_growlee_setup(merchant):
    campaign, _ = Campaign.objects.get_or_create(
        merchant=merchant,
        name='Campagne de bienvenue',
        defaults={
            'game_type': 'spin',
            'reward_label': 'Offre exclusive sur votre prochaine visite',
            'landing_headline': 'Tentez votre chance',
            'landing_subheadline': 'Un jeu rapide pour découvrir votre surprise du jour.',
            'cta_label': 'Jouer maintenant',
            'journey_type': 'premium_mobile',
            'review_enabled': True,
            'wallet_enabled': True,
            'is_active': True,
        },
    )

    entry_point, _ = EntryPoint.objects.get_or_create(
        merchant=merchant,
        campaign=campaign,
        code=f'{merchant.slug}-qr-main',
        defaults={
            'name': 'QR principal',
            'channel': 'qr',
            'placement': 'counter',
        },
    )

    reward, _ = Reward.objects.get_or_create(
        merchant=merchant,
        campaign=campaign,
        name='Offre de bienvenue',
        defaults={
            'reward_type': 'custom',
            'description': 'Offre exclusive sur votre prochaine visite',
            'probability_weight': 100,
            'daily_quota': 50,
            'active': True,
            'expires_in_hours': 168,
        },
    )

    if not WheelSegment.objects.filter(campaign=campaign).exists():
        WheelSegment.objects.create(campaign=campaign, reward=reward, label='Gain principal', probability_weight=65, daily_quota=50, display_order=1, color='#f59e0b', active=True)
        WheelSegment.objects.create(campaign=campaign, reward=reward, label='Petit bonus', probability_weight=25, daily_quota=50, display_order=2, color='#fb7185', active=True)
        WheelSegment.objects.create(campaign=campaign, reward=reward, label='Jackpot', probability_weight=10, daily_quota=20, display_order=3, color='#60a5fa', active=True)

    return campaign, entry_point, reward


def _ensure_spin_defaults(campaign):
    if campaign is None or campaign.game_type not in {'spin', 'scratch'}:
        return
    active_segments = WheelSegment.objects.filter(campaign=campaign, active=True)
    if active_segments.count() >= 3:
        return
    reward = Reward.objects.filter(campaign=campaign, active=True).order_by('-probability_weight', 'id').first()
    defaults = [
        ('Gain principal', 65, 50, 1, '#f59e0b'),
        ('Petit bonus', 25, 50, 2, '#fb7185'),
        ('Jackpot', 10, 20, 3, '#60a5fa'),
    ]
    existing_labels = set(active_segments.values_list('label', flat=True))
    for label, weight, quota, order, color in defaults:
        if label in existing_labels:
            continue
        WheelSegment.objects.create(campaign=campaign, reward=reward, label=label, probability_weight=weight, daily_quota=quota, display_order=order, color=color, active=True)


@login_required
@merchant_unlocked_required
def merchant_checkout(request):
    membership = MerchantMembership.objects.select_related('merchant').filter(user=request.user).first()
    merchant = membership.merchant if membership else None
    if merchant is None:
        messages.error(request, 'Aucun commerce lié à ce compte.')
        return redirect('admin-dashboard')
    payment_link = settings.GROWLEE_PAYMENT_LINK_PRO
    if payment_link:
        return redirect(payment_link)
    messages.info(request, 'Checkout Growlee prêt : configurez GROWLEE_PAYMENT_LINK_PRO pour activer le lien de paiement externe.')
    return render(request, 'admin/pending_payment.html', {'merchant': merchant, 'pricing_plans': _pricing_plans()})


@login_required
@merchant_unlocked_required
def merchant_onboarding(request):
    membership = MerchantMembership.objects.select_related('merchant').filter(user=request.user).first()
    merchant = membership.merchant if membership else None
    if merchant is None:
        messages.error(request, 'Aucun commerce lié à ce compte.')
        return redirect('admin-dashboard')
    if request.method == 'GET' and request.path == '/admin/onboarding/' and merchant.onboarding_completed:
        context = _merchant_context_for_user(request.user)
        if context.get('campaign') is None:
            _ensure_default_growlee_setup(merchant)
            context = _merchant_context_for_user(request.user)
        return render(request, 'admin/configuration.html', context)
    merchant_form = MerchantForm(
        request.POST or None,
        request.FILES or None,
        instance=merchant,
        prefix='merchant',
    )
    if request.method == 'POST' and request.POST.get('form_action') == 'flyer_approve':
        if not merchant.onboarding_completed:
            messages.error(request, 'Complétez d’abord les informations commerce avant de valider le flyer.')
            return redirect('merchant-account')
        merchant.flyer_visual_approved = True
        merchant.flyer_order_status = 'visual_approved_waiting_payment'
        merchant.save(update_fields=['flyer_visual_approved', 'flyer_order_status'])
        messages.success(request, 'Visuel flyer validé. Il reste le paiement onboarding de 80€ pour débloquer l’application et lancer la commande.')
        return redirect('merchant-account')

    if request.method == 'POST' and request.POST.get('form_action') == 'merchant_identity' and merchant_form.is_valid():
        merchant = merchant_form.save(commit=False)
        if merchant.billing_payment_type and not merchant.payment_method:
            merchant.payment_method = 'Carte bancaire' if merchant.billing_payment_type == 'cb' else 'IBAN / prélèvement'
        required = {
            'Nom': merchant.name,
            'Adresse': merchant.address,
            'Secteur d’activité': merchant.business_sector,
            'Email de contact': merchant.contact_email,
            'Offre flyers': merchant.flyer_offer,
        }
        missing = [label for label, value in required.items() if not (value or '').strip()]
        if missing:
            messages.error(request, 'Champs obligatoires manquants : ' + ', '.join(missing) + '.')
            return redirect('merchant-account')
        if not merchant.flyer_style:
            merchant.flyer_style = 'premium'
        merchant.onboarding_completed = True
        merchant.flyer_visual_approved = True
        merchant.flyer_order_status = 'visual_approved_waiting_payment'
        merchant.save()
        merchant_form.save_m2m()
        campaign, entry_point, reward = _ensure_default_growlee_setup(merchant)
        if merchant.is_active:
            messages.success(request, 'Onboarding enregistré. Votre dashboard, votre QR code et votre parcours client personnalisé sont prêts.')
            return redirect('admin-dashboard')
        messages.success(request, 'Onboarding enregistré. Vos informations sont sauvegardées : vous pouvez revenir payer ou demander une activation par facturation directe plus tard.')
        return redirect('merchant-account')

    context = _merchant_context_for_user(request.user)
    latest_campaign = Campaign.objects.filter(merchant=merchant).order_by('-created_at', '-id').first()
    qr_entry = None
    nfc_entry = None
    entry_form = None
    qr_svg = ''
    if latest_campaign:
        qr_entry, _ = EntryPoint.objects.get_or_create(
            merchant=merchant,
            campaign=latest_campaign,
            code=f'{merchant.slug}-qr-main',
            defaults={'name': 'QR principal', 'channel': 'qr', 'placement': 'table'},
        )
        nfc_entry, _ = EntryPoint.objects.get_or_create(
            merchant=merchant,
            campaign=latest_campaign,
            code=f'{merchant.slug}-nfc-card',
            defaults={'name': 'Carte NFC', 'channel': 'nfc', 'placement': 'carte'},
        )
        entry_form = EntryPointForm(request.POST or None, instance=qr_entry, prefix='entry')
        if request.method == 'POST' and request.POST.get('form_action') == 'entry_point' and entry_form.is_valid():
            entry_form.save()
            messages.success(request, 'Redirection QR/NFC mise à jour.')
            return redirect('merchant-account')
        if qr_entry:
            logo_url = _merchant_logo_for_svg(merchant)
            qr_svg = build_qr_svg(
                data=f"{settings.APP_BASE_URL}/go/{qr_entry.code}/",
                merchant_name=merchant.name,
                primary_color=merchant.primary_color,
                accent_color=merchant.accent_color,
                logo_url=logo_url,
                size=420,
            )
    context.update({'merchant_form': merchant_form, 'campaign': latest_campaign, 'qr_entry_code': qr_entry.code if qr_entry else '', 'nfc_entry_code': nfc_entry.code if nfc_entry else '', 'entry_form': entry_form, 'qr_svg': qr_svg})
    return render(request, 'admin/onboarding.html', context)


merchant_account = merchant_onboarding


@login_required
@merchant_unlocked_required
def game_configuration(request):
    context = _merchant_context_for_user(request.user)
    merchant = context['merchant']
    if merchant is None:
        messages.error(request, 'Aucun commerce lié à ce compte.')
        return redirect('admin-dashboard')

    campaign = Campaign.objects.filter(merchant=merchant).order_by('-created_at', '-id').first()
    campaign_form = CampaignForm(request.POST or None, instance=campaign, prefix='campaign')
    merchant_style_form = MerchantForm(request.POST or None, request.FILES or None, instance=merchant, prefix='merchant-style')
    reward_form = RewardForm(request.POST or None, prefix='reward', initial={
        'reward_type': 'gift',
        'probability_weight': 100,
        'daily_quota': 50,
        'expires_in_hours': 168,
        'active': True,
    })

    if request.method == 'POST':
        action = request.POST.get('form_action')
        if action == 'reward' and reward_form.is_valid():
            reward = reward_form.save(commit=False)
            reward.merchant = merchant
            reward.campaign = campaign
            reward.save()
            messages.success(request, 'Récompense ajoutée au jeu.')
            return redirect('game-configuration')
        if action == 'merchant_style' and merchant_style_form.is_valid():
            merchant_style_form.save()
            messages.success(request, 'Personnalisation du parcours client mise à jour.')
            return redirect('game-configuration')
        if action != 'merchant_style' and campaign_form.is_valid():
            campaign = campaign_form.save(commit=False)
            campaign.merchant = merchant
            campaign.save()
            if campaign.game_type in {'spin', 'scratch'}:
                _ensure_spin_defaults(campaign)
            messages.success(request, 'Configuration mini jeu mise à jour.')
            return redirect('game-configuration')

    entry_point = EntryPoint.objects.filter(merchant=merchant, campaign=campaign).order_by('-created_at', '-id').first() if campaign else None
    if campaign and entry_point is None:
        entry_point, _ = EntryPoint.objects.get_or_create(
            merchant=merchant,
            campaign=campaign,
            code=f'{merchant.slug}-qr-main',
            defaults={'name': 'QR principal', 'channel': 'qr', 'placement': 'counter'},
        )
    segments = WheelSegment.objects.filter(campaign=campaign).select_related('reward').order_by('display_order', 'id') if campaign else []
    rewards = Reward.objects.filter(merchant=merchant).order_by('name')
    total_weight = sum(segment.probability_weight for segment in segments if segment.active)
    context.update({'campaign': campaign, 'campaign_form': campaign_form, 'segments': segments, 'total_weight': total_weight, 'merchant_form': merchant_style_form, 'rewards': rewards, 'reward_form': reward_form, 'qr_entry_code': entry_point.code if entry_point else ''})
    return render(request, 'admin/game_config.html', context)


@login_required
@merchant_unlocked_required
def review_configuration(request):
    context = _merchant_context_for_user(request.user)
    merchant = context['merchant']
    form = MerchantReviewForm(request.POST or None, instance=merchant, prefix='merchant-review')
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Lien Google de l’établissement mis à jour.')
        return redirect('review-configuration')
    context.update({'merchant_form': form})
    return render(request, 'admin/review.html', context)


@login_required
@merchant_unlocked_required
def toggle_campaign_flag(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    context = _merchant_context_for_user(request.user)
    merchant = context['merchant']
    campaign = context['campaign']
    if campaign is None and merchant:
        campaign, _entry_point, _reward = _ensure_default_growlee_setup(merchant)
    campaign_id = request.POST.get('campaign_id')
    if campaign_id and merchant:
        campaign = Campaign.objects.filter(id=campaign_id, merchant=merchant).first() or campaign
    if campaign is None:
        messages.error(request, 'Aucune campagne à modifier.')
        return redirect('merchant-onboarding')
    flag = request.POST.get('flag')
    requested = request.POST.get('value')
    desired = (requested == '1') if requested in {'0', '1'} else None
    labels = {
        'is_active': 'Jeu',
        'review_enabled': 'Avis',
        'wallet_enabled': 'Wallet',
    }
    if flag in labels:
        current = getattr(campaign, flag)
        next_value = desired if desired is not None else (not current)
        setattr(campaign, flag, next_value)
        campaign.save(update_fields=[flag])
        messages.success(request, f'Module {labels[flag]} {"activé" if next_value else "désactivé"}.')
    else:
        messages.error(request, 'Option inconnue.')
    return redirect(request.POST.get('next') or 'merchant-onboarding')



@login_required
def wallet_pass_scan(request, scan_code):
    membership = MerchantMembership.objects.select_related('merchant').filter(user=request.user).first()
    merchant = membership.merchant if membership else None
    wallet_pass = WalletPass.objects.select_related('customer', 'campaign', 'campaign__merchant').filter(scan_code=scan_code).first()
    if wallet_pass is None:
        return render(request, 'admin/wallet_scan.html', {
            'merchant': merchant,
            'wallet_pass': None,
            'customer': None,
            'campaign': None,
            'is_complete': False,
            'scan_code': scan_code,
            'scan_error': 'Aucun pass wallet ne correspond à ce code. Utilisez le QR généré dans un vrai pass client.',
        }, status=404)
    if merchant is None or wallet_pass.campaign.merchant_id != merchant.id:
        messages.error(request, 'Ce pass wallet ne correspond pas à votre commerce.')
        return redirect('admin-dashboard')

    if request.method == 'POST':
        wallet_pass.stamps = min(wallet_pass.stamps + 1, wallet_pass.stamps_target)
        wallet_pass.payload = build_wallet_payload(
            GameSession.objects.filter(customer=wallet_pass.customer, campaign=wallet_pass.campaign).select_related('customer', 'campaign__merchant', 'reward').order_by('-created_at').first(),
            wallet_pass.provider,
            wallet_pass,
        ) if GameSession.objects.filter(customer=wallet_pass.customer, campaign=wallet_pass.campaign).exists() else wallet_pass.payload
        wallet_pass.save(update_fields=['stamps', 'payload', 'updated_at'])
        messages.success(request, f'Passage validé. Total: {wallet_pass.stamps}/{wallet_pass.stamps_target}.')
        return redirect('wallet-pass-scan', scan_code=scan_code)

    return render(request, 'admin/wallet_scan.html', {
        'merchant': merchant,
        'wallet_pass': wallet_pass,
        'customer': wallet_pass.customer,
        'campaign': wallet_pass.campaign,
        'is_complete': wallet_pass.stamps >= wallet_pass.stamps_target,
    })

@login_required
@merchant_unlocked_required
def wallet_configuration(request):
    context = _merchant_context_for_user(request.user)
    return render(request, 'admin/wallet.html', context)


@login_required
@merchant_unlocked_required
def merchant_setup(request):
    return redirect('game-configuration')
    membership = MerchantMembership.objects.select_related('merchant').filter(user=request.user).first()
    merchant = membership.merchant if membership else None
    if merchant is None:
        messages.error(request, 'Aucun commerce lié à ce compte.')
        return redirect('admin-dashboard')

    campaign = Campaign.objects.filter(merchant=merchant).order_by('-created_at', '-id').first()
    if campaign is None:
        campaign, entry_point, reward = _ensure_default_growlee_setup(merchant)
    entry_point = EntryPoint.objects.filter(merchant=merchant, campaign=campaign).order_by('-created_at', '-id').first() if campaign else EntryPoint.objects.filter(merchant=merchant).order_by('-created_at', '-id').first()
    if entry_point is None:
        entry_point, _ = EntryPoint.objects.get_or_create(
            merchant=merchant,
            campaign=campaign,
            code=f'{merchant.slug}-qr-main',
            defaults={'name': 'QR principal', 'channel': 'qr', 'placement': 'counter'},
        )

    created = request.GET.get('created') == '1'
    qr_entry_code = request.GET.get('entry') or (entry_point.code if entry_point else '')

    return render(request, 'admin/merchant/setup.html', {
        'merchant': merchant,
        'created': created,
        'qr_entry_code': qr_entry_code,
    })


@login_required
def qr_preview(request, code):
    entry_point = get_object_or_404(EntryPoint.objects.select_related('merchant'), code=code)
    if not request.user.is_superuser and not MerchantMembership.objects.filter(user=request.user, merchant=entry_point.merchant).exists():
        messages.error(request, 'Ce QR ne correspond pas à votre commerce.')
        return redirect('admin-dashboard')
    url = f"{settings.APP_BASE_URL}/go/{entry_point.code}/"
    logo_url = _merchant_logo_for_svg(entry_point.merchant)
    svg = build_qr_svg(
        data=url,
        merchant_name=entry_point.merchant.name,
        primary_color=entry_point.merchant.primary_color,
        accent_color=entry_point.merchant.accent_color,
        logo_url=logo_url,
    )
    return HttpResponse(svg, content_type='image/svg+xml')


def entry_redirect(request, code):
    entry_point = get_object_or_404(EntryPoint, code=code)
    target = entry_point.redirect_url or f'/play/{entry_point.merchant.slug}/'
    return redirect(target)


@login_required
@merchant_unlocked_required
def customers_list(request):
    membership = MerchantMembership.objects.select_related('merchant').filter(user=request.user).first()
    merchant = membership.merchant if membership else None
    if merchant is None:
        messages.error(request, 'Aucun commerce lié à ce compte.')
        return redirect('admin-dashboard')

    query = (request.GET.get('q') or '').strip()
    customers = Customer.objects.filter(merchant=merchant).order_by('-created_at')
    if query:
        customers = customers.filter(
            Q(phone__icontains=query) |
            Q(email__icontains=query) |
            Q(first_name__icontains=query)
        )
    customers = customers[:100]
    for customer in customers:
        customer.latest_session = customer.game_sessions.select_related('reward').order_by('-created_at').first()
    return render(request, 'admin/customers.html', {
        'merchant': merchant,
        'customers': customers,
        'query': query,
    })


@login_required
@merchant_unlocked_required
def customer_detail(request, customer_id):
    membership = MerchantMembership.objects.select_related('merchant').filter(user=request.user).first()
    merchant = membership.merchant if membership else None
    customer = get_object_or_404(Customer, id=customer_id, merchant=merchant)
    sessions = customer.game_sessions.select_related('campaign', 'reward').order_by('-created_at')
    return render(request, 'admin/customer_detail.html', {
        'customer': customer,
        'sessions': sessions,
    })


@login_required
@merchant_unlocked_required
def delete_customer(request, customer_id):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    membership = MerchantMembership.objects.select_related('merchant').filter(user=request.user).first()
    merchant = membership.merchant if membership else None
    customer = get_object_or_404(Customer, id=customer_id, merchant=merchant)
    phone = customer.phone
    customer.delete()
    messages.success(request, f'Client supprimé: {phone}.')
    return redirect('customers-list')


@login_required
@merchant_unlocked_required
def customers_export_csv(request):
    membership = MerchantMembership.objects.select_related('merchant').filter(user=request.user).first()
    merchant = membership.merchant if membership else None
    if merchant is None:
        return redirect('admin-dashboard')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="growlee-customers-{merchant.slug}.csv"'
    writer = csv.writer(response)
    writer.writerow(['phone', 'first_name', 'email', 'created_at', 'sessions_count'])
    for customer in Customer.objects.filter(merchant=merchant).order_by('-created_at'):
        writer.writerow([
            customer.phone,
            customer.first_name,
            customer.email,
            customer.created_at.isoformat(),
            customer.game_sessions.count(),
        ])
    return response


@login_required
@merchant_unlocked_required
def rewards_list(request):
    if request.method == 'GET':
        return redirect('game-configuration')
    context = _merchant_context_for_user(request.user)
    merchant = context['merchant']
    rewards = Reward.objects.filter(merchant=merchant).order_by('name') if merchant else []
    reward_form = RewardForm(request.POST or None, prefix='reward', initial={
        'reward_type': 'gift',
        'probability_weight': 100,
        'daily_quota': 50,
        'expires_in_hours': 168,
        'active': True,
    })

    if request.method == 'POST' and merchant and reward_form.is_valid():
        reward = reward_form.save(commit=False)
        reward.merchant = merchant
        reward.campaign = context['campaign']
        reward.save()
        messages.success(request, 'Récompense enregistrée.')
        return redirect('game-configuration')

    context['rewards'] = rewards
    context['reward_form'] = reward_form
    return render(request, 'admin/rewards.html', context)


@login_required
@merchant_unlocked_required
def reward_delete(request, reward_id):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    membership = MerchantMembership.objects.select_related('merchant').filter(user=request.user).first()
    merchant = membership.merchant if membership else None
    reward = get_object_or_404(Reward, id=reward_id, merchant=merchant)
    reward.delete()
    messages.success(request, 'Récompense supprimée.')
    return redirect('game-configuration')


@login_required
@merchant_unlocked_required
def analytics_view(request):
    context = _merchant_context_for_user(request.user)
    return render(request, 'admin/analytics.html', context)


@login_required
@merchant_unlocked_required
def automations_view(request):
    context = _merchant_context_for_user(request.user)
    campaign = context['campaign']
    if request.method == 'POST' and campaign:
        schedule_enabled = request.POST.get('schedule_enabled') == '1'
        date_str = request.POST.get('scheduled_date') or ''
        time_str = request.POST.get('scheduled_time') or ''
        if schedule_enabled and date_str and time_str:
            dt = datetime.fromisoformat(f"{date_str}T{time_str}:00")
            campaign.send_immediately = False
            campaign.scheduled_for = timezone.make_aware(dt, timezone.get_current_timezone())
        else:
            campaign.send_immediately = True
            campaign.scheduled_for = None
        campaign.save(update_fields=['send_immediately', 'scheduled_for'])
        messages.success(request, 'Planification de campagne mise à jour.')
        return redirect('automations-view')
    return render(request, 'admin/automations.html', context)


@login_required
@merchant_unlocked_required
def redeem_session(request, session_id):
    if request.method != 'POST':
        return redirect('admin-dashboard')
    membership = MerchantMembership.objects.select_related('merchant').filter(user=request.user).first()
    merchant = membership.merchant if membership else None
    session = get_object_or_404(GameSession.objects.select_related('customer', 'campaign'), id=session_id, customer__merchant=merchant)
    if not session.redeemed:
        session.redeemed = True
        session.save(update_fields=['redeemed'])
        messages.success(request, f'Gain marqué comme utilisé pour {session.customer.phone}.')
    return redirect('customer-detail', customer_id=session.customer_id)


@login_required
@merchant_unlocked_required
def employee_mode(request):
    merchant = _current_merchant(request)
    if merchant is None:
        messages.error(request, 'Aucun commerce lié à ce compte.')
        return redirect('admin-dashboard')
    request.session['growlee_employee_mode'] = True
    found_session = None
    query = (request.POST.get('scan_code') or request.GET.get('scan_code') or '').strip()

    if request.method == 'POST' and request.POST.get('action') == 'redeem':
        session = get_object_or_404(GameSession.objects.select_related('customer', 'campaign'), id=request.POST.get('session_id'), campaign__merchant=merchant)
        if session.redeemed:
            messages.info(request, 'Ce gain a déjà été utilisé.')
        elif not session.is_recovery_window_open:
            messages.error(request, 'Fenêtre expirée : le client doit recliquer sur “Récupérer mon gain”.')
        else:
            session.redeemed = True
            session.save(update_fields=['redeemed'])
            messages.success(request, f'Gain validé : {session.reward_label}.')
        return redirect('employee-mode')

    if query:
        lookup_code = query.rstrip('/').split('/')[-1] if '/gain/' in query else query
        found_session = GameSession.objects.select_related('customer', 'campaign', 'reward').filter(
            campaign__merchant=merchant
        ).filter(Q(claim_code__iexact=lookup_code) | Q(claim_token__iexact=lookup_code)).order_by('-created_at').first()
        if not found_session:
            messages.error(request, 'Aucun gain trouvé pour ce code ou cette carte.')

    return render(request, 'admin/employee.html', {
        'merchant': merchant,
        'scan_code': query,
        'found_session': found_session,
    })


@login_required
@merchant_unlocked_required
def employee_exit(request):
    merchant = _current_merchant(request)
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == 'POST':
        unlock_pin = (request.POST.get('unlock_pin') or '').strip()
        if unlock_pin and merchant and unlock_pin == merchant.employee_pin:
            request.session.pop('growlee_employee_mode', None)
            messages.success(request, 'Mode employeur réouvert par PIN.')
            return redirect('admin-dashboard')
        if form.is_valid():
            user = form.get_user()
            allowed = MerchantMembership.objects.filter(
                user=user,
                merchant=merchant,
                role__in=['owner', 'manager'],
            ).exists()
            if allowed:
                login(request, user)
                request.session.pop('growlee_employee_mode', None)
                messages.success(request, 'Mode employeur réouvert.')
                return redirect('admin-dashboard')
            messages.error(request, 'Ce compte n’a pas les droits employeur pour ce commerce.')
        else:
            messages.error(request, 'Identifiant ou mot de passe incorrect.')
    return render(request, 'admin/employee_exit.html', {'merchant': merchant, 'form': form})


@rate_limit('reward_claim', limit=20, limit_setting='RATELIMIT_GAIN_ATTEMPTS', window=3600)
def reward_claim_page(request, token):
    session = get_object_or_404(
        GameSession.objects.select_related('customer', 'campaign__merchant', 'reward'),
        claim_token=token,
    )
    now = timezone.now()
    expired = bool(session.reward_expires_at and session.reward_expires_at < now)
    if request.method == 'POST' and not expired and not session.redeemed:
        session.reward_available_until = now + timedelta(minutes=15)
        session.save(update_fields=['reward_available_until'])
        messages.success(request, 'Votre gain est disponible pendant 15 minutes. Présentez cet écran au point de vente.')
        return redirect('reward-claim-page', token=token)
    return render(request, 'public/reward_claim.html', {
        'session': session,
        'merchant': session.campaign.merchant,
        'expired': expired,
        'window_open': session.is_recovery_window_open,
        'claim_url': reward_claim_url(session),
        'claim_qr': generate_qr_data_uri(reward_claim_url(session), fill_color=session.campaign.merchant.primary_color or '#111827'),
    })


def _font_stack(font_key):
    mapping = {
        'inter': 'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
        'poppins': 'Poppins, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
        'manrope': 'Manrope, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
        'dm-sans': '"DM Sans", ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    }
    return mapping.get(font_key, mapping['inter'])



def _latest_session_for_wallet(request, slug):
    merchant = get_object_or_404(Merchant, slug=slug, is_active=True)
    campaign = _get_active_campaign_for_merchant(merchant)
    session_id = request.session.get(f'growlee_last_session_{merchant.slug}')
    session = None
    if session_id and campaign:
        session = GameSession.objects.filter(id=session_id, campaign=campaign).select_related('customer', 'campaign__merchant', 'reward').first()
    if session is None and campaign:
        session = GameSession.objects.filter(campaign=campaign).select_related('customer', 'campaign__merchant', 'reward').order_by('-created_at').first()
    if session is None:
        raise Http404('Aucune session de jeu disponible pour générer le wallet.')
    return session


def apple_wallet_pass(request, slug):
    session = _latest_session_for_wallet(request, slug)
    wallet_pass = issue_wallet_pass_placeholder(session, 'apple')
    if wallet_pass.status != 'ready':
        return render(request, 'public/wallet_pending.html', {
            'merchant': session.campaign.merchant,
            'provider': 'Apple Wallet',
            'wallet_pass': wallet_pass,
            'config_status': wallet_config_status(),
        }, status=501)
    # Futur branchement: retourner FileResponse(open(pkpass_path, 'rb'), content_type='application/vnd.apple.pkpass')
    return render(request, 'public/wallet_pending.html', {
        'merchant': session.campaign.merchant,
        'provider': 'Apple Wallet',
        'wallet_pass': wallet_pass,
        'config_status': wallet_config_status(),
    })


def google_wallet_pass(request, slug):
    session = _latest_session_for_wallet(request, slug)
    wallet_pass = issue_wallet_pass_placeholder(session, 'google')
    if wallet_pass.status != 'ready' or not wallet_pass.pass_url:
        return render(request, 'public/wallet_pending.html', {
            'merchant': session.campaign.merchant,
            'provider': 'Google Wallet',
            'wallet_pass': wallet_pass,
            'config_status': wallet_config_status(),
        }, status=501)
    return redirect(wallet_pass.pass_url)

@rate_limit('play_page', limit=30, limit_setting='RATELIMIT_PLAY_POST_ATTEMPTS', window=3600)
def play_page(request, slug):
    merchant = get_object_or_404(Merchant, slug=slug, is_active=True)
    # Le parcours public ne dépend plus uniquement du module Jeu.
    # La campagne courante porte aussi les modules Avis / Wallet et la collecte d'infos.
    campaign = Campaign.objects.filter(merchant=merchant).order_by('-created_at', '-id').first()
    if campaign is None:
        return render(request, 'public/play.html', {
            'merchant': merchant,
            'campaign': None,
            'entry_point': None,
            'form': ClaimRewardForm(),
            'recent_sessions': [],
            'step': 'inactive',
            'claimed_session': None,
            'wheel_segments': [],
            'total_weight': 0,
            'heading_font_stack': _font_stack(getattr(merchant, 'heading_font', 'inter')),
            'body_font_stack': _font_stack(getattr(merchant, 'body_font', 'inter')),
            'game_step_count': 0,
            'wallet_enabled': False,
        })
    entry_point = EntryPoint.objects.filter(merchant=merchant, campaign=campaign).order_by('-created_at', '-id').first()
    game_enabled = bool(campaign.is_active)
    review_enabled = bool(campaign.review_enabled)
    wallet_enabled = bool(campaign.wallet_enabled)
    if game_enabled and campaign.game_type in {'spin', 'scratch'}:
        _ensure_spin_defaults(campaign)
    step = request.GET.get('step', 'landing')
    if step in {'game'} and not game_enabled:
        step = 'landing'
    if step == 'review' and not review_enabled:
        step = 'wallet' if wallet_enabled else 'landing'
    if step == 'wallet' and not wallet_enabled:
        step = 'landing'

    if request.method == 'POST':
        form = ClaimRewardForm(request.POST)
        if form.is_valid():
            customer, session, segment = claim_reward(
                merchant=merchant,
                campaign=campaign,
                phone=form.cleaned_data['phone'],
                email=form.cleaned_data.get('email', ''),
                first_name=form.cleaned_data.get('first_name', ''),
                consent=form.cleaned_data.get('consent', False),
            )
            request.session[f'growlee_last_session_{merchant.slug}'] = session.id
            send_reward_notifications(session)
            next_step = 'reward' if game_enabled else ('review' if review_enabled else ('wallet' if wallet_enabled else 'landing'))
            return redirect(f"/play/{slug}/?step={next_step}")
        step = 'collect'
    else:
        form = ClaimRewardForm()

    session_id = request.session.get(f'growlee_last_session_{merchant.slug}')
    claimed_session = None
    if session_id:
        claimed_session = GameSession.objects.filter(id=session_id, campaign=campaign).select_related('customer', 'reward').first()

    recent_sessions = GameSession.objects.filter(campaign=campaign).select_related('customer').order_by('-created_at')[:5]
    wheel_segments = WheelSegment.objects.filter(campaign=campaign, active=True).select_related('reward').order_by('display_order', 'id')
    total_weight = sum(segment.probability_weight for segment in wheel_segments)
    return render(request, 'public/play.html', {
        'merchant': merchant,
        'campaign': campaign,
        'entry_point': entry_point,
        'form': form,
        'recent_sessions': recent_sessions,
        'step': step,
        'claimed_session': claimed_session,
        'wheel_segments': wheel_segments,
        'total_weight': total_weight,
        'heading_font_stack': _font_stack(getattr(merchant, 'heading_font', 'inter')),
        'body_font_stack': _font_stack(getattr(merchant, 'body_font', 'inter')),
        'game_step_count': 4 if review_enabled and wallet_enabled else (3 if review_enabled or wallet_enabled else 2),
        'game_enabled': game_enabled,
        'review_enabled': review_enabled,
        'wallet_enabled': wallet_enabled,
        'google_review_url': merchant.google_review_url,
    })
