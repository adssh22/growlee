from django.db import OperationalError, connection

from apps.core.common_views import *  # noqa: F401,F403
from apps.core.common_views import (  # noqa: F401
    _admin_access_block_response,
    _control_access_granted,
    _current_merchant,
    _employee_mode_block_response,
    _ensure_default_growlee_setup,
    _ensure_spin_defaults,
    _first_membership,
    _font_stack,
    _get_active_campaign_for_merchant,
    _latest_session_for_wallet,
    _merchant_context_for_user,
    _merchant_is_unlocked,
    _merchant_logo_for_svg,
    _pricing_plans,
    _staff_mfa_for_user,
    _staff_mfa_qr_context,
    _unique_merchant_slug,
)

def healthz(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
    except OperationalError:
        return JsonResponse({'status': 'unhealthy'}, status=503)
    return JsonResponse({'status': 'ok'})


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

