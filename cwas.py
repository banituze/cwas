#!/usr/bin/env python3
"""
Community Water Access Scheduler
Main Application Entry Point with Complete Functionality
"""

import os
import sys
import hashlib
import secrets
import sqlite3
import csv
from datetime import datetime, timedelta
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def clear_screen():
    """Clear terminal screen for better UX"""
    os.system('cls' if os.name == 'nt' else 'clear')

def hash_password(password, salt=None):
    """Hash password with salt for security"""
    if salt is None:
        salt = secrets.token_hex(16)
    return hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000).hex(), salt

def verify_password(password, hashed_password, salt):
    """Verify password against hash"""
    return hashed_password == hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000).hex()

class DatabaseManager:
    def __init__(self, db_path='water_scheduler.db'):
        self.db_path = db_path
        self.init_database()
    
    def get_connection(self):
        return sqlite3.connect(self.db_path)
    
    def init_database(self):
        """Initialize database with user authentication"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Users table for authentication
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                username VARCHAR(50) UNIQUE NOT NULL,
                email VARCHAR(100) UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                role VARCHAR(20) NOT NULL,
                household_id INTEGER,
                verification_code TEXT,
                is_verified BOOLEAN DEFAULT FALSE,
                created_date DATE DEFAULT CURRENT_DATE,
                last_login DATETIME,
                status VARCHAR(20) DEFAULT 'active',
                FOREIGN KEY (household_id) REFERENCES households(household_id)
            )
        ''')
        
        # Households table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS households (
                household_id INTEGER PRIMARY KEY AUTOINCREMENT,
                family_name VARCHAR(100) NOT NULL,
                contact_phone VARCHAR(20),
                contact_email VARCHAR(100),
                family_size INTEGER NOT NULL,
                priority_level VARCHAR(20) DEFAULT 'normal',
                address TEXT,
                registration_date DATE DEFAULT CURRENT_DATE,
                status VARCHAR(20) DEFAULT 'active',
                balance DECIMAL(10,2) DEFAULT 0.00,
                monthly_allowance INTEGER DEFAULT 1000,
                CHECK (family_size > 0),
                CHECK (priority_level IN ('high', 'normal', 'low')),
                CHECK (status IN ('active', 'inactive', 'suspended'))
            )
        ''')
        
        # Water sources table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS water_sources (
                source_id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_name VARCHAR(100) NOT NULL,
                source_type VARCHAR(50) NOT NULL,
                location TEXT NOT NULL,
                capacity_per_hour INTEGER NOT NULL,
                operating_start_time TIME NOT NULL,
                operating_end_time TIME NOT NULL,
                status VARCHAR(20) DEFAULT 'active',
                price_per_100L DECIMAL(5,2) DEFAULT 0.05,
                priority_access TEXT DEFAULT 'all',
                created_date DATE DEFAULT CURRENT_DATE,
                CHECK (capacity_per_hour > 0),
                CHECK (source_type IN ('Well', 'Borehole', 'Tap', 'Spring', 'Tank')),
                CHECK (status IN ('active', 'inactive', 'maintenance')),
                CHECK (operating_end_time > operating_start_time)
            )
        ''')
        
        # Time slots table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS time_slots (
                slot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL,
                slot_date DATE NOT NULL,
                start_time TIME NOT NULL,
                end_time TIME NOT NULL,
                max_households INTEGER NOT NULL,
                current_bookings INTEGER DEFAULT 0,
                status VARCHAR(20) DEFAULT 'available',
                priority_reserved INTEGER DEFAULT 0,
                FOREIGN KEY (source_id) REFERENCES water_sources(source_id),
                CHECK (max_households > 0),
                CHECK (current_bookings >= 0),
                CHECK (current_bookings <= max_households),
                CHECK (status IN ('available', 'full', 'maintenance', 'cancelled')),
                CHECK (end_time > start_time),
                UNIQUE(source_id, slot_date, start_time, end_time)
            )
        ''')
        
        # Bookings table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bookings (
                booking_id INTEGER PRIMARY KEY AUTOINCREMENT,
                household_id INTEGER NOT NULL,
                slot_id INTEGER NOT NULL,
                booking_date DATE DEFAULT CURRENT_DATE,
                booking_status VARCHAR(20) DEFAULT 'pending',
                collection_status VARCHAR(20) DEFAULT 'pending',
                actual_collection_time DATETIME,
                water_amount_collected INTEGER,
                amount_charged DECIMAL(8,2),
                satisfaction_rating INTEGER,
                notes TEXT,
                approval_date DATETIME,
                receipt_number VARCHAR(50),
                FOREIGN KEY (household_id) REFERENCES households(household_id),
                FOREIGN KEY (slot_id) REFERENCES time_slots(slot_id),
                CHECK (booking_status IN ('pending', 'approved', 'denied', 'cancelled', 'completed')),
                CHECK (collection_status IN ('pending', 'completed', 'missed')),
                CHECK (water_amount_collected IS NULL OR water_amount_collected > 0),
                CHECK (satisfaction_rating IS NULL OR (satisfaction_rating >= 1 AND satisfaction_rating <= 5)),
                UNIQUE(household_id, slot_id)
            )
        ''')
        
        # Notifications table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notifications (
                notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                household_id INTEGER,
                title VARCHAR(200) NOT NULL,
                message TEXT NOT NULL,
                notification_type VARCHAR(50) NOT NULL,
                is_read BOOLEAN DEFAULT FALSE,
                created_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (household_id) REFERENCES households(household_id)
            )
        ''')
        
        # Receipts table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS receipts (
                receipt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                receipt_number VARCHAR(50) UNIQUE NOT NULL,
                household_id INTEGER NOT NULL,
                booking_id INTEGER NOT NULL,
                amount DECIMAL(8,2) NOT NULL,
                water_amount INTEGER NOT NULL,
                issue_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                payment_method VARCHAR(20) DEFAULT 'account_balance',
                FOREIGN KEY (household_id) REFERENCES households(household_id),
                FOREIGN KEY (booking_id) REFERENCES bookings(booking_id)
            )
        ''')
        
        conn.commit()
        conn.close()

class AuthenticationManager:
    def __init__(self, db_manager):
        self.db = db_manager
    
    def register_user(self, role):
        """Register new user with role-specific requirements"""
        clear_screen()
        print(f"\n=== REGISTER NEW {role.upper()} ===")
        
        # Admin registration requires verification code
        if role == 'admin':
            verification_code = input("Enter system administrator verification code: ").strip()
            if verification_code != "cwas2025":
                print("Invalid verification code. Access denied.")
                input("Press Enter to continue...")
                return None
        
        # Coordinator registration requires verification code
        if role == 'coordinator':
            verification_code = input("Enter coordinator verification code: ").strip()
            if verification_code != "cwas2005":
                print("Invalid verification code. Access denied.")
                input("Press Enter to continue...")
                return None
        
        username = input("Choose username: ").strip()
        if not username or len(username) < 3:
            print("Username must be at least 3 characters long.")
            input("Press Enter to continue...")
            return None
        
        email = input("Enter email address: ").strip()
        if not self.validate_email(email):
            print("Invalid email format.")
            input("Press Enter to continue...")
            return None
        
        password = input("Enter password (min 6 characters): ").strip()
        if len(password) < 6:
            print("Password must be at least 6 characters long.")
            input("Press Enter to continue...")
            return None
        
        confirm_password = input("Confirm password: ").strip()
        if password != confirm_password:
            print("Passwords do not match.")
            input("Press Enter to continue...")
            return None
        
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            # Check if username or email exists
            cursor.execute("SELECT user_id FROM users WHERE username = ? OR email = ?", (username, email))
            if cursor.fetchone():
                print("Username or email already exists.")
                conn.close()
                input("Press Enter to continue...")
                return None
            
            password_hash, salt = hash_password(password)
            household_id = None
            
            # For household users, create household first
            if role == 'household':
                household_id = self.create_household_profile(cursor)
                if not household_id:
                    conn.close()
                    return None
            
            cursor.execute('''
                INSERT INTO users (username, email, password_hash, salt, role, household_id, is_verified)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (username, email, password_hash, salt, role, household_id, True))
            
            user_id = cursor.lastrowid
            conn.commit()
            conn.close()
            
            print(f"\nRegistration successful! User ID: {user_id}")
            if role == 'household' and household_id:
                print(f"Household ID: {household_id}")
            
            input("Press Enter to continue...")
            return user_id
            
        except Exception as e:
            print(f"Registration failed: {e}")
            input("Press Enter to continue...")
            return None
    
    def create_household_profile(self, cursor):
        """Create household profile during registration"""
        print("\n--- Household Information ---")
        family_name = input("Family name: ").strip()
        if not family_name:
            print("Family name is required.")
            return None
        
        contact_phone = input("Contact phone: ").strip()
        family_size = input("Family size: ").strip()
        try:
            family_size = int(family_size)
            if family_size <= 0:
                print("Family size must be greater than 0.")
                return None
        except ValueError:
            print("Invalid family size.")
            return None
        
        priority_level = input("Priority level (high/normal/low) [normal]: ").strip() or 'normal'
        if priority_level not in ['high', 'normal', 'low']:
            priority_level = 'normal'
        
        address = input("Address: ").strip()
        
        cursor.execute('''
            INSERT INTO households (family_name, contact_phone, family_size, 
                                  priority_level, address, balance)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (family_name, contact_phone, family_size, priority_level, address, 50.00))
        
        return cursor.lastrowid
    
    def login_user(self):
        """User login"""
        clear_screen()
        print("\n=== LOGIN ===")
        
        username = input("Username: ").strip()
        password = input("Password: ").strip()
        
        if not username or not password:
            print("Username and password are required.")
            input("Press Enter to continue...")
            return None
        
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT user_id, password_hash, salt, role, household_id, status
                FROM users WHERE username = ?
            ''', (username,))
            
            user = cursor.fetchone()
            if not user:
                print("Invalid username or password.")
                conn.close()
                input("Press Enter to continue...")
                return None
            
            user_id, password_hash, salt, role, household_id, status = user
            
            if status != 'active':
                print("Account is inactive. Contact administrator.")
                conn.close()
                input("Press Enter to continue...")
                return None
            
            if not verify_password(password, password_hash, salt):
                print("Invalid username or password.")
                conn.close()
                input("Press Enter to continue...")
                return None
            
            # Update last login
            cursor.execute("UPDATE users SET last_login = ? WHERE user_id = ?", 
                          (datetime.now().isoformat(' '), user_id))
            conn.commit()
            conn.close()
            
            print(f"Login successful! Welcome back.")
            input("Press Enter to continue...")
            return {
                'user_id': user_id,
                'username': username,
                'role': role,
                'household_id': household_id
            }
            
        except Exception as e:
            print(f"Login failed: {e}")
            input("Press Enter to continue...")
            return None
    
