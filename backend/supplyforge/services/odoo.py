import xmlrpc.client
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

class OdooIntegrationService:
    @staticmethod
    def get_odoo_config():
        """Get Odoo configuration from settings with sensible fallbacks."""
        odoo_cfg = settings.SUPPLYFORGE.get('odoo', {})
        return {
            'url': odoo_cfg.get('url', 'http://34.130.191.122'),
            'db': odoo_cfg.get('db', 'odoo'),
            'username': odoo_cfg.get('username', 'admin'),
            'password': odoo_cfg.get('password', 'admin'),  # API Key or Password
        }

    @staticmethod
    def sync_user_to_odoo(name, email, phone=None):
        """
        Creates a contact (res.partner) in Odoo 18 with user info.
        Prevents duplicates by checking if the email already exists in res.partner.
        """
        cfg = OdooIntegrationService.get_odoo_config()
        url = cfg['url'].rstrip('/')
        db = cfg['db']
        username = cfg['username']
        password = cfg['password']

        # Extract base server URL (scheme + netloc) to bypass any /odoo or web paths
        from urllib.parse import urlparse
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        
        common_url = f"{base_url}/xmlrpc/2/common"
        object_url = f"{base_url}/xmlrpc/2/object"

        logger.info(f"[Odoo Sync] Connecting to Odoo at: {common_url} (DB: {db}, User: {username})")

        try:
            import socket
            # Set short non-blocking timeout for Odoo RPC so auth calls stay fast
            class TimeoutTransport(xmlrpc.client.Transport):
                timeout = 2.0
                def make_connection(self, host):
                    conn = super().make_connection(host)
                    conn.timeout = self.timeout
                    return conn

            transport = TimeoutTransport()
            common = xmlrpc.client.ServerProxy(common_url, transport=transport)
            uid = common.authenticate(db, username, password, {})
            
            if not uid:
                logger.error("[Odoo Sync] Authentication failed. Check Odoo credentials.")
                return None

            # 2. Connect to Odoo object service
            models = xmlrpc.client.ServerProxy(object_url)

            # 3. Check if contact already exists by email to prevent duplicate res.partner
            existing_partners = models.execute_kw(
                db, uid, password,
                'res.partner', 'search',
                [[('email', '=', email)]]
            )

            if existing_partners:
                partner_id = existing_partners[0]
                logger.info(f"[Odoo Sync] Contact with email {email} already exists in Odoo (ID: {partner_id}). Updating details.")
                
                # Update contact details (phone, name) in Odoo
                update_vals = {}
                if phone:
                    update_vals['phone'] = phone
                if name:
                    update_vals['name'] = name
                    
                if update_vals:
                    models.execute_kw(
                        db, uid, password,
                        'res.partner', 'write',
                        [[partner_id], update_vals]
                    )
                return partner_id

            # 4. Create new contact
            partner_vals = {
                'name': name,
                'email': email,
                'phone': phone or '',
                'is_company': False,
                'comment': 'Created automatically via SupplyForge AI Login sync.',
            }

            partner_id = models.execute_kw(
                db, uid, password,
                'res.partner', 'create',
                [partner_vals]
            )

            logger.info(f"[Odoo Sync] Created contact '{name}' successfully in Odoo (ID: {partner_id}).")
            return partner_id

        except Exception as e:
            logger.error(f"[Odoo Sync Error] Failed to sync to Odoo: {str(e)}")
            return None
