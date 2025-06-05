# Security Policy for PAPRI AI Video Search Engine

## Reporting a Vulnerability

The PAPRI AI team and community take security bugs in PAPRI seriously. We appreciate your efforts to responsibly disclose your findings, and will make every effort to acknowledge your contributions.

To report a security vulnerability, please email our security team at `security@papri.example.com` (replace with your actual security email) with a detailed description of the vulnerability, steps to reproduce it, and any potential impact. Please include "PAPRI Security Vulnerability Report" in the subject line.

**Do not report security vulnerabilities through public GitHub issues, social media, or other public channels.**

We will endeavor to:
- Acknowledge receipt of your vulnerability report within 48 hours.
- Provide an estimated timeframe for addressing the vulnerability.
- Notify you when the vulnerability has been fixed.

We kindly ask you not to disclose the vulnerability publicly until we have had a reasonable time to address it.

## Key Security Measures Implemented

PAPRI AI implements several security measures to protect its users and data. This is not an exhaustive list but highlights key areas:

1.  **Authentication & Authorization:**
    * Robust user authentication using Django Allauth, supporting email/password and potential social logins.
    * Password hashing and secure password reset mechanisms provided by Django.
    * API endpoints protected with appropriate permissions (e.g., `IsAuthenticated`, `IsAdminUser`). Session-based authentication for web clients.

2.  **Data Protection:**
    * **HTTPS Enforcement:** In production environments, PAPRI should be deployed exclusively over HTTPS to encrypt data in transit. (Deployment responsibility)
    * **Sensitive Data Handling:** User passwords are hashed. API keys and sensitive credentials (database passwords, `SECRET_KEY`) are managed via environment variables and `python-dotenv` (not hardcoded).
    * **CSRF Protection:** Django's built-in CSRF (Cross-Site Request Forgery) protection is enabled for form submissions and state-changing requests.
    * **Input Validation:** Serializers and forms are used to validate incoming data to prevent common injection attacks for API and web inputs.

3.  **API Security:**
    * **Rate Limiting:** `django-ratelimit` is implemented on sensitive or computationally expensive API endpoints to prevent abuse and ensure service availability. This includes endpoints for search initiation and AI video editor task creation. (See `settings.py` for specific rates).
    * **CORS Configuration:** Cross-Origin Resource Sharing (CORS) is configured to allow requests only from trusted frontend domains in production.

4.  **Infrastructure & Deployment:**
    * **Environment Variables:** All sensitive configurations are loaded from environment variables, not committed to the codebase.
    * **Regular Updates:** Dependencies are managed via `requirements.txt` and should be regularly updated to patch known vulnerabilities. (Operational responsibility)
    * **Logging:** Comprehensive logging is in place to monitor application behavior and detect suspicious activities.

5.  **Code Quality & Development Practices:**
    * Code reviews are part of the development process.
    * Use of linters and formatters to maintain code quality.
    * Development follows Django's security best practices.

## Future Considerations (Roadmap)

* Implementation of more granular object-level permissions.
* Formal security audits.
* Advanced anomaly detection for API usage.
* Two-Factor Authentication (2FA) for user accounts.

We are committed to continuously improving the security of the PAPRI AI platform.
