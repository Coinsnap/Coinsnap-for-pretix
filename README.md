# Coinsnap for Pretix payment plugin #
![Coinsnap for Pretix](https://resources.coinsnap.org/products/pretix/images/cover.png)

## Accept Bitcoin and Lightning Payments with Coinsnap in Pretix ##

* Contributors: coinsnap
* Tags: Lightning, Lightning Payment, SATS, Satoshi sats, bitcoin, Pretix, accept bitcoin, bitcoin plugin, bitcoin payment processor, bitcoin e-commerce, Lightning Network, cryptocurrency, lightning payment processor
* Requires Python: 3.5
* Stable tag: 0.9.0
* License: GPL2
* License URI: https://www.gnu.org/licenses/gpl-2.0.html

The Coinsnap Pretix plugin allows you to accept Bitcoin Lightning payments in Pretix ticket store.

## Description ##

![Pretix ticket sale system](https://resources.coinsnap.org/products/pretix/images/screenshot-pretix.png)

* Coinsnap Pretix Demo Site: https://pretix.coinsnap.net/
* Blog Article: https://coinsnap.io/en/coinsnap-for-pretix/
* GitHub: https://github.com/Coinsnap/Coinsnap-for-pretix

## Bitcoin and Lightning payments in Pretix ##




## Features ##

* **All you need is your email and a Lightning Wallet with a Lightning address. [Here you can find an overview of suitable Lightning Wallets](https://coinsnap.io/en/lightning-wallet-with-lightning-address/)**

* **Accept Bitcoin and Lightning payments** in your online store **without running your own technical infrastructure.** You do not need your own server, nor do you need to run your own Lightning Node. You also do not need a shop-system, for you can sell right out of your forms using the Coinsnap for Content Form 7-plugin.

* **Quick and easy registration at Coinsnap**: Just enter your email address and your Lightning address – and you are ready to integrate the payment module and start selling for Bitcoin Lightning. You will find the necessary IDs and Keys in your Coinsnap account, too.

* **100% protected privacy**:
    * We do not collect personal data.
    * For the registration you only need an e-mail address, which we will also use to inform you when you have received a payment.
    * No other personal information is required as long as you request a withdrawal to a Lightning address or Bitcoin address.

* **Only 1 % fees!**:
    * No basic fee, no transaction fee, only 1% on the invoice amount with referrer code.
    * Without referrer code the fee is 1.25%.
    * Get a referrer code from our [partners](https://coinsnap.io/en/partner/) and customers and save 0.25% fee.

* **No KYC needed**:
    * Direct, P2P payments (instantly to your Lightning wallet)
    * No intermediaries and paperwork
    * Transaction information is only shared between you and your customer

* **Sophisticated merchant’s admin dashboard in Coinsnap:**:
    * See all your transactions at a glance
    * Follow-up on individual payments
    * See issues with payments
    * Export reports

* **A Bitcoin payment via Lightning offers significant advantages**:
    * Lightning **payments are executed immediately.**
    * Lightning **payments are credited directly to the recipient.**
    * Lightning **payments are inexpensive.**
    * Lightning **payments are guaranteed.** No chargeback risk for the merchant.
    * Lightning **payments can be used worldwide.**
    * Lightning **payments are perfect for micropayments.**

* **Multilingual interface and support**: We speak your language


## Documentation: ##

* [Coinsnap API (1.0) documentation](https://docs.coinsnap.io/)
* [Frequently Asked Questions](https://coinsnap.io/en/faq/) 
* [Terms and Conditions](https://coinsnap.io/en/general-terms-and-conditions/)
* [Privacy Policy](https://coinsnap.io/en/privacy/)

## Installation ##

### 1. Coinsnap plugin installation

Setup dev environment as described here https://docs.pretix.eu/en/latest/development/setup.html

After successfully setting up dev environment copy coinsnap folder from our repo https://github.com/Coinsnap/Coinsnap-for-pretix  to src folder of Pretix.

Run:
3.1. Inside src/coinsnap folder pip3 install -e.
3.2. Inside src folder of pretix
python manage.py makemigrations coinsnap
python manage.py migrate
3.3. Inside src folder
python manage.py runserver


### 2. Connect Coinsnap account with Pretix ###

After you have installed Coinsnap plugin, you need to connect to Coinsnap App. 

2.1. Go to **http://localhost:8000/control** or **http(s)://<yourdomain>/control** and log in. 

Default credentials are: 
- e-Mail: **admin@localhost**
- password: **admin**

2.2. Click on **Admin Mode** in upper right corner and create new Organizer under Organizers in navbar.

2.3. Create new Event (every event can have its own payment gateways list).

2.4. After creating event go to **Settings > Plugins** and enable **Coinsnap**.

2.5. Go to Settings > Payment > Settings next to Bitcoin-Lightning payment and click **Enable payment method** and at the bottom add **StoreID** and **Api Key** and ngrok domain as **Custom domain** if you are on localhost in order to make webhooks work.


### 3. Create Coinsnap account ####

### 3.1. Create a Coinsnap Account ####

Now go to the Coinsnap website at: https://app.coinsnap.io/register and open an account by entering your email address and a password of your choice.

![Create a Coinsnap Account](https://resources.coinsnap.org/products/pretix/images/screenshot-8.png)

If you are using a Lightning Wallet with Lightning Login, then you can also open a Coinsnap account with it. 	

### 3.2. Confirm email address ####

You will receive an email to the given email address with a confirmation link, which you have to confirm. If you do not find the email, please check your spam folder.

![Confirm email address](https://resources.coinsnap.org/products/pretix/images/screenshot-9.png)

Then please log in to the Coinsnap backend with the appropriate credentials.

### 3.3. Set up website at Coinsnap ###

After you sign up, you will be asked to provide two pieces of information.

In the Website Name field, enter the name of your online store that you want customers to see when they check out.

In the Lightning Address field, enter the Lightning address to which the Bitcoin and Lightning transactions should be forwarded.

A Lightning address is similar to an e-mail address. Lightning payments are forwarded to this Lightning address and paid out. If you don’t have a Lightning address yet, set up a Lightning wallet that will provide you with a Lightning address.

![Set up website at Coinsnap](https://resources.coinsnap.org/products/pretix/images/screenshot-10.png)

For more information on Lightning addresses and the corresponding Lightning wallet providers, click here:
https://coinsnap.io/lightning-wallet-mit-lightning-adresse/

After saving settings you can use Store ID and Api Key on the step 2.


### 4. Test Coinsnap payment for ticket in Pretix ###

Every event has its own URL, user can choose needed options and order tickets according to the event settings. 

4.1. Go to event URL, which you can find on event page in Backend.

![Event page](https://resources.coinsnap.org/products/pretix/images/screenshot-11.png)

4.2. Choose needed event options and add ticket to cart.

![Shopping cart](https://resources.coinsnap.org/products/pretix/images/screenshot-12.png)

4.3. Go to checkout. Add your contact data and continue.

![Add your contact data](https://resources.coinsnap.org/products/pretix/images/screenshot-13.png)

4.4. Select Bitcoin-Lightning payment as payment method and continue. 

![Select Bitcoin-Lightning payment](https://resources.coinsnap.org/products/pretix/images/screenshot-14.png)

4.5. Review order and click `Place binding order`.

![Order review](https://resources.coinsnap.org/products/pretix/images/screenshot-15.png)

4.6. You'll see QR code for payment. Hold your wallet above it and the amount of SATS displayed above will be transferred from your wallet to the Coinsnap wallet as soon as you click the button “pay”.

![QR code for payment](https://resources.coinsnap.org/products/pretix/images/screenshot-16.png)


