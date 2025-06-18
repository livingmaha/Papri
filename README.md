# Papri Project

Papri is a modern web application designed to [**Describe the main purpose of Papri here. e.g., "discover and share recipes from around the world"**]. It features a powerful API backend, an intelligent data scraping agent, and a dynamic user interface.

## ✨ Features

* **RESTful API**: A robust backend built with Django and Django REST Framework.
* **Social Authentication**: Easy sign-up and login using social accounts (e.g., Google) via `django-allauth`.
* **AI Data Scraper**: A Scrapy-based agent to gather relevant data from the web.
* **Separated Frontend**: A clean architecture with a decoupled frontend for a better user experience.
* **Cloud Media Storage**: Scalable media file management using Cloudinary.

---

## 🚀 Getting Started

Follow these instructions to get a copy of the project up and running on your local machine for development and testing purposes.

### Prerequisites

* Python 3.8+
* Poetry (for dependency management) or pip
* Git

### Installation

1.  **Clone the repository:**
    ```sh
    git clone [https://github.com/livingmugash/papri_project_root.git](https://github.com/livingmugash/papri_project_root.git)
    cd papri_project_root
    ```

2.  **Navigate to the backend directory:**
    ```sh
    cd backend
    ```

3.  **Set up the Python virtual environment:**
    ```sh
    python -m venv venv
    source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
    ```

4.  **Install dependencies:**
    ```sh
    pip install -r requirements.txt
    ```

5.  **Set up environment variables:**
    * Copy the example file: `cp ../.env.example .env`
    * Open the `.env` file and fill in the required values (especially `SECRET_KEY` and `DATABASE_URL`).

6.  **Run database migrations:**
    ```sh
    python manage.py migrate
    ```

7.  **Run the development server:**
    ```sh
    python manage.py runserver
    ```

The API will now be available at `http://127.0.0.1:8000`.

---

## 🚢 Deployment

The project is designed to be deployed using Docker for consistency and ease of setup. See the deployment guide for detailed instructions on deploying the backend and database to a production server.

## Built With

* [**Django**](https://www.djangoproject.com/) - The web framework for perfectionists with deadlines.
* [**Django REST Framework**](https://www.django-rest-framework.org/) - A powerful toolkit for building Web APIs.
* [**Scrapy**](https://scrapy.org/) - An open source and collaborative framework for extracting the data you need from websites.
* [**PostgreSQL**](https://www.postgresql.org/) - A powerful, open source object-relational database system.
