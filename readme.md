# Securing Your VM Lab URL with Cloudflare Zero Trust & OAuth

This guide covers the next steps after successfully exposing your Raspberry Pi Docker container/VM to your custom domain via Cloudflare Tunnel. Here, we will configure **Cloudflare Access** to restrict public traffic and add **Google and GitHub OAuth** authentication so only authorized users can access your lab.

---

## Prerequisites
* Your VM container running locally on your Raspberry Pi (e.g., `https://192.168.29.23:3001`).
* Your domain active on Cloudflare with an active Tunnel pointing to a subdomain (e.g., `vm.curiosity4u.in`).

---

## Step 1: Set Up Cloudflare Zero Trust Access

To protect your publicly exposed lab from unauthorized access, you need to gate it behind Cloudflare Access.

1. Navigate to the [Cloudflare Zero Trust Dashboard](https://one.dash.cloudflare.com/) and select your account.
2. In the left sidebar, go to **Access** > **Applications**.
3. Click **Add an application** and select **Self-Hosted**.
4. Configure the application details:
   * **Application name:** `VM Lab Security`
   * **Session Duration:** `24 hours` (or your preferred duration)
   * **Subdomain:** `vm.curiosity4u.in` (matching your setup)
5. Click **Next**.

---

## Step 2: Configure Allowed Email Rules

1. Define a policy name (e.g., `Allowed Lab Members`).
2. Set the **Action** to **Allow**.
3. Under **Configure rules**, choose a selector:
   * Select **Emails** to whitelist individual email addresses.
   * Select **Emails domain** to allow an entire organization domain (e.g., `@yourdomain.com`).
4. Click **Next**, then **Add application**.

---

## Step 3: Add Google and GitHub OAuth Authentication

To allow users to log in smoothly using their existing Google or GitHub accounts:

### 1. Enable Login Methods in Cloudflare
1. In the Cloudflare Zero Trust sidebar, navigate to **Settings** > **Authentication**.
2. Under **Login methods**, click **Add new**.
3. Select **Google** and/or **GitHub**.

### 2. Configure OAuth Credentials
* **For Google:**
  1. Go to the [Google Cloud Console](https://console.cloud.google.com/) and create an OAuth 2.0 Client ID.
  2. Set the authorized redirect URI to the callback URL provided by Cloudflare.
  3. Copy your **Client ID** and **Client Secret** back into Cloudflare.
* **For GitHub:**
  1. Go to your GitHub account **Settings** > **Developer settings** > **OAuth Apps** > **New OAuth App**.
  2. Paste the callback URL provided by Cloudflare into the Authorization callback URL field.
  3. Generate and copy your **Client ID** and **Client Secret** into Cloudflare.

### 3. Attach OAuth to Your Application
1. Go back to **Access** > **Applications** and click on your `VM Lab Security` application.
2. Navigate to the **Authentication** tab.
3. Check the boxes for **Google** and **GitHub** (along with One-Time PIN if desired) and save your changes.

---

## Verification

Open `https://vm.curiosity4u.in` in an **Incognito / Private browsing window**. 

Instead of loading your VM directly, Cloudflare will present a secure login page with options to authenticate via Google, GitHub, or email OTP. Only users matching your email whitelist rules will be granted access to your lab environment.