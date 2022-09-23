[![Build Status](https://travis-ci.org/rebkwok/freedom_of_flight.svg?branch=master)](https://travis-ci.org/rebkwok/freedom_of_flight)
[![Coverage Status](https://coveralls.io/repos/github/rebkwok/freedom_of_flight/badge.svg?branch=master)](https://coveralls.io/github/rebkwok/freedom_of_flight?branch=master)
## bookings website

# Required settings

- SECRET_KEY: app secret key
- DATABASE_URL: database settings
- EMAIL_HOST_PASSWORD: password for emails sent from the app
- DEFAULT_PAYPAL_EMAIL: the email address paypal payments made through the app will be sent to
- LOG_FOLDER: path to folder containing the app's log files
- PAYPAL_IDENTITY_TOKEN
- INVOICE_KEY
- STRIPE_PUBLISHABLE_KEY
- STRIPE_CONNECT_CLIENT_ID
- STRIPE_SECRET_KEY
- STRIPE_ENDPOINT_SECRET

## Stripe
In stripe account, add auth callback uri to:
<https://dashboard.stripe.com/settings/connect>

And webhook to:
<https://dashboard.stripe.com/webhooks>


# Optional
- DEBUG (default False)
- SEND_ALL_STUDIO_EMAILS (default False)
- LOCAL (default False)
- USE_CDN (CDN static files; defaults to !DEBUG)

# For dev add the following additional settings to .env
- DEBUG=True
- USE_MAILCATCHER=True
- LOCAL=True
- PAYPAL_TEST=True
- SHOW_DEBUG_TOOLBAR=True
