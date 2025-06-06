# Security Policy for PAPRI AI

**IMPORTANT PRE-DEPLOYMENT CHECK:** The vulnerability reporting email address (`security@papri.example.com`) MUST be configured as a functional, regularly monitored inbox BEFORE the application is deployed to any public-facing environment. Failure to do so will result in missed security vulnerability reports.

## Reporting a Vulnerability

The PAPRI AI team and community take security bugs in PAPRI seriously. We appreciate your efforts to responsibly disclose your findings, and will make every effort to acknowledge your contributions.

To report a security vulnerability, please email our security team at `security@papri.example.com` with a detailed description of the vulnerability, steps to reproduce it, and any potential impact. Please include "PAPRI Security Vulnerability Report" in the subject line.

**Do not report security vulnerabilities through public GitHub issues, social media, or other public channels.**

We will endeavor to:
- Acknowledge receipt of your vulnerability report within 48 hours.
- Provide an estimated timeframe for addressing the vulnerability.
- Notify you when the vulnerability has been fixed.

We kindly ask you not to disclose the vulnerability publicly until we have had a reasonable time to address it.

## Key Security Measures Implemented

1.  **Authentication & Authorization:**
    * Robust user authentication using Django Allauth, supporting email/password and potential social logins.
    * Password hashing and secure password reset mechanisms provided by Django.
    * API endpoints protected with appropriate permissions (e.g., `IsAuthenticated`, `IsAdminUser`). Session-based authentication for web clients.

2.  **Data Protection:**
    * **HTTPS Enforcement:** In production environments, PAPRI is deployed exclusively over HTTPS to encrypt data in transit.
    * **Sensitive Data Handling:** User passwords are hashed. API keys and sensitive credentials (database passwords, `SECRET_KEY`) are managed via environment variables and not hardcoded.
    * **CSRF Protection:** Django's built-in CSRF (Cross-Site Request Forgery) protection is enabled.

3.  **API Security:**
    * **Rate Limiting:** `django-ratelimit` is implemented on sensitive API endpoints to prevent abuse.
    * **CORS Configuration:** Cross-Origin Resource Sharing (CORS) is configured to allow requests only from trusted frontend domains in production.

4.  **Infrastructure & Deployment:**
    * **Environment Variables:** All sensitive configurations are loaded from environment variables.
    * **Regular Updates:** Dependencies are managed via `requirements.txt` and should be regularly updated.
