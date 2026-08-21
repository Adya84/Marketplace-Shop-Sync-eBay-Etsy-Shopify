# Shop Sync Privacy Policy

**Last updated: 21 August 2026**

Shop Sync helps users manage and transfer marketplace listings between supported services including eBay, Etsy, TikTok Shop and Shopify.

## Information Shop Sync accesses

When you connect a marketplace account, Shop Sync may access information made available through that marketplace's API and authorised by you. Depending on the service and permissions granted, this may include:

- Account and marketplace identifiers
- Shop or store information
- Product and inventory listings
- Listing titles, descriptions, images, prices, quantities and related listing data
- Information required to create, update, import, export or synchronise listings
- OAuth access and refresh credentials required to maintain an authorised connection

Shop Sync does not request or store your marketplace password. Marketplace sign-in is performed by the marketplace provider using its official authorisation process.

## How information is used

Information accessed through connected marketplace APIs is used only to provide Shop Sync functionality, including importing, exporting, creating, updating and synchronising listings between services selected by the user.

Shop Sync does not sell personal information or marketplace account data to third parties.

## Data storage and security

Marketplace data and saved marketplace credentials are normally stored inside the user's own Shop Sync Home Assistant installation. Shop Sync uses an installation-specific authenticated credential wrapper for locally saved secrets.

Users are responsible for protecting their Home Assistant installation, backups and local Shop Sync data.

## eBay OAuth broker

Shop Sync uses a hosted OAuth broker for eBay so ordinary users do not need their own eBay Developer account and the Shop Sync eBay client secret is not distributed inside the public Home Assistant application.

During eBay connection and token renewal, the broker temporarily processes information required by eBay's OAuth flow. This can include the single-use eBay authorisation code, OAuth state, refresh token and token response. These values are processed only to complete the requested eBay authorisation or token refresh and are returned to the user's Shop Sync installation for local storage.

The broker is designed to operate without a persistent database of seller tokens. OAuth secrets and token values should not be intentionally written to application logs.

## Third-party services

Shop Sync connects to third-party services such as eBay, Etsy, TikTok Shop and Shopify. Use of those services remains subject to their respective terms, privacy policies and developer/API requirements.

Shop Sync requests only API permissions needed for the features being used. Users can revoke Shop Sync's access through the relevant marketplace account where supported.

## Data retention and deletion

Marketplace data and saved credentials are normally retained in the user's own Shop Sync installation for as long as required to provide the configured functionality.

Users can stop future access by revoking Shop Sync in the relevant marketplace account and removing locally stored Shop Sync credentials or application data.

The hosted eBay OAuth broker is designed not to retain seller OAuth tokens after completing the individual authorisation or refresh request.

## eBay data

When a user authorises Shop Sync to access eBay, Shop Sync uses eBay-authorised API access only for functionality requested by the user, such as reading and managing inventory and listings. Access is limited by the OAuth scopes granted by the user.

## Changes to this policy

This privacy policy may be updated as Shop Sync gains new features, marketplace integrations or data-handling requirements. Updates will be published in this repository.

## Contact

Questions, privacy requests or issues relating to Shop Sync can be submitted through the project's GitHub repository:

https://github.com/Adya84/Marketplace-Shop-Sync-eBay-Etsy-Shopify
