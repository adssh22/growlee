import hashlib
import secrets
from dataclasses import dataclass
from typing import Literal

from django.conf import settings
from django.utils import timezone

from apps.customers.models import GameSession, WalletPass

Provider = Literal['apple', 'google']


@dataclass(frozen=True)
class WalletConfigStatus:
    apple_ready: bool
    google_ready: bool
    missing: list[str]


def wallet_config_status() -> WalletConfigStatus:
    required_apple = [
        'APPLE_WALLET_PASS_TYPE_ID',
        'APPLE_WALLET_TEAM_ID',
        'APPLE_WALLET_CERT_PATH',
        'APPLE_WALLET_KEY_PATH',
    ]
    required_google = [
        'GOOGLE_WALLET_ISSUER_ID',
        'GOOGLE_WALLET_SERVICE_ACCOUNT_PATH',
    ]
    missing = [name for name in required_apple + required_google if not getattr(settings, name, '')]
    return WalletConfigStatus(
        apple_ready=not any(name in missing for name in required_apple),
        google_ready=not any(name in missing for name in required_google),
        missing=missing,
    )


def wallet_serial(provider: Provider, session: GameSession) -> str:
    raw = f'{provider}:{session.id}:{session.customer_id}:{session.campaign_id}'
    digest = hashlib.sha256(raw.encode('utf-8')).hexdigest()[:18]
    return f'growlee-{provider}-{digest}'


def build_wallet_payload(session: GameSession, provider: Provider, wallet_pass: WalletPass | None = None) -> dict:
    merchant = session.campaign.merchant
    reward = session.reward_label
    scan_url = ''
    stamps = 0
    stamps_target = 5
    if wallet_pass and wallet_pass.scan_code:
        base_url = getattr(settings, 'APP_BASE_URL', '').rstrip('/')
        scan_url = f'{base_url}/admin/wallet/scan/{wallet_pass.scan_code}/'
        stamps = wallet_pass.stamps
        stamps_target = wallet_pass.stamps_target
    return {
        'provider': provider,
        'merchant': {
            'name': merchant.name,
            'slug': merchant.slug,
            'primaryColor': merchant.primary_color,
            'accentColor': merchant.accent_color,
        },
        'customer': {
            'id': session.customer_id,
            'firstName': session.customer.first_name,
            'phone': session.customer.phone,
            'email': session.customer.email,
        },
        'campaign': {
            'id': session.campaign_id,
            'name': session.campaign.name,
        },
        'reward': {
            'label': reward,
            'claimCode': session.claim_code,
            'redeemed': session.redeemed,
        },
        'loyalty': {
            'stamps': stamps,
            'stampsTarget': stamps_target,
            'label': 'Carte de fidélité',
            'subtitle': f'{stamps}/{stamps_target} passages validés',
        },
        'scan': {
            'code': wallet_pass.scan_code if wallet_pass else '',
            'url': scan_url,
            'barcodeFormat': 'PKBarcodeFormatQR',
            'messageEncoding': 'iso-8859-1',
            'purpose': 'merchant_checkin',
        },
    }


def get_or_prepare_wallet_pass(session: GameSession, provider: Provider) -> WalletPass:
    serial = wallet_serial(provider, session)
    wallet_pass, _ = WalletPass.objects.get_or_create(
        provider=provider,
        serial_number=serial,
        defaults={
            'customer': session.customer,
            'campaign': session.campaign,
            'auth_token': secrets.token_urlsafe(32),
            'scan_code': secrets.token_urlsafe(24),
            'stamps': 0,
            'stamps_target': 5,
            'status': 'draft',
        },
    )
    if not wallet_pass.scan_code:
        wallet_pass.scan_code = secrets.token_urlsafe(24)
    wallet_pass.customer = session.customer
    wallet_pass.campaign = session.campaign
    wallet_pass.payload = build_wallet_payload(session, provider, wallet_pass)
    wallet_pass.save(update_fields=['customer', 'campaign', 'scan_code', 'payload', 'updated_at'])
    return wallet_pass


def issue_wallet_pass_placeholder(session: GameSession, provider: Provider) -> WalletPass:
    wallet_pass = get_or_prepare_wallet_pass(session, provider)
    status = wallet_config_status()
    ready = status.apple_ready if provider == 'apple' else status.google_ready
    if not ready:
        wallet_pass.status = 'draft'
        wallet_pass.error_message = 'Configuration fournisseur manquante: ' + ', '.join(status.missing)
    else:
        # Hook prêt pour brancher la vraie génération plus tard :
        # - Apple: signer le bundle .pkpass puis stocker/servir le fichier.
        # - Google: créer la class/object via API puis stocker le saveUrl.
        wallet_pass.status = 'ready'
        wallet_pass.issued_at = timezone.now()
        wallet_pass.error_message = ''
    wallet_pass.save(update_fields=['status', 'issued_at', 'error_message', 'updated_at'])
    return wallet_pass
