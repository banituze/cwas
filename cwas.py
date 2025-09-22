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
import time

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
        conn = sqlite3.connect(self.db_path, timeout=10)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA busy_timeout = 8000")
            conn.execute("PRAGMA journal_mode = WAL")
        except Exception:
            pass
        return conn
    

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
                payment_method VARCHAR(20),
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
        
        # Lightweight migration: ensure bookings.payment_method exists
        try:
            cursor.execute("PRAGMA table_info(bookings);")
            cols = [r[1] for r in cursor.fetchall()]
            if 'payment_method' not in cols:
                cursor.execute("ALTER TABLE bookings ADD COLUMN payment_method VARCHAR(20)")
        except Exception:
            pass
        
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
    
    def validate_email(self, email):
        """Validate email format"""
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return re.match(pattern, email) is not None

class WaterSchedulerApp:
    def __init__(self):
        self.db = DatabaseManager()
        self.auth = AuthenticationManager(self.db)
        self.current_user = None
    
    def display_welcome(self):
        """Display welcome screen"""
        clear_screen()
        print("\n" + "="*60)
        print("    COMMUNITY WATER ACCESS SCHEDULER")
        print("="*60)
        print("Welcome to the Community Water Access Scheduler!")
        print("This system helps manage fair access to shared water sources.")
        print("Water collection pricing: $0.05 per 100L container")
        print("="*60)
    
    def main_menu(self):
        """Main authentication menu"""
        while True:
            clear_screen()
            self.display_welcome()
            print("\n=== MAIN MENU ===")
            print("1. Login")
            print("2. Register as Household Member")
            print("3. Register as Coordinator")
            print("4. Register as System Administrator")
            print("5. Exit System")
            
            choice = input("\nEnter your choice (1-5): ").strip()
            
            if choice == '1':
                user = self.auth.login_user()
                if user:
                    self.current_user = user
                    self.route_user_menu()
            elif choice == '2':
                self.auth.register_user('household')
            elif choice == '3':
                self.auth.register_user('coordinator')
            elif choice == '4':
                self.auth.register_user('admin')
            elif choice == '5':
                print("\nThank you for using the Community Water Access Scheduler!")
                break
            else:
                print("Invalid choice. Please select 1-5.")
                input("Press Enter to continue...")
    
    def route_user_menu(self):
        """Route user to appropriate menu"""
        while self.current_user:
            if self.current_user['role'] == 'household':
                self.household_menu()
            elif self.current_user['role'] == 'coordinator':
                self.coordinator_menu()
            elif self.current_user['role'] == 'admin':
                self.admin_menu()
    
    def household_menu(self):
        """Household member menu"""
        while True:
            clear_screen()
            print(f"\n=== HOUSEHOLD MENU ===")
            print(f"Welcome, {self.current_user['username']}!")
            
            # Show account balance
            balance = self.get_household_balance()
            print(f"Account Balance: ${balance:.2f}")
            
            print("\n1. Make Water Collection Booking")
            print("2. View My Bookings")
            print("3. Cancel Booking")
            print("4. View Available Water Sources")
            print("5. View My Receipts")
            print("6. Add Funds to Account")
            print("7. View Notifications")
            print("8. Update Profile")
            print("9. Logout")
            
            choice = input("\nEnter your choice (1-9): ").strip()
            
            if choice == '1':
                self.make_booking()
            elif choice == '2':
                self.view_my_bookings()
            elif choice == '3':
                self.cancel_booking()
            elif choice == '4':
                self.view_water_sources()
            elif choice == '5':
                self.view_receipts()
            elif choice == '6':
                self.add_funds()
            elif choice == '7':
                self.view_notifications()
            elif choice == '8':
                self.update_profile()
            elif choice == '9':
                self.current_user = None
                return
            else:
                print("Invalid choice.")
                input("Press Enter to continue...")
    
    def coordinator_menu(self):
        """Coordinator menu"""
        while True:
            clear_screen()
            print(f"\n=== COORDINATOR MENU ===")
            print(f"Welcome, {self.current_user['username']}!")
            print("\n1. Manage Water Sources")
            print("2. Review Booking Requests")
            print("3. Generate Time Slots")
            print("4. View Daily Summary")
            print("5. Generate Reports")
            print("6. Export Data")
            print("7. Send Notifications")
            print("8. Manage Households")
            print("9. Logout")
            
            choice = input("\nEnter your choice (1-9): ").strip()
            
            if choice == '1':
                self.manage_water_sources()
            elif choice == '2':
                self.review_bookings()
            elif choice == '3':
                self.generate_time_slots()
            elif choice == '4':
                self.view_daily_summary()
            elif choice == '5':
                self.generate_reports()
            elif choice == '6':
                self.export_data()
            elif choice == '7':
                self.send_notifications()
            elif choice == '8':
                self.manage_households()
            elif choice == '9':
                self.current_user = None
                return
            else:
                print("Invalid choice.")
                input("Press Enter to continue...")
    
    def admin_menu(self):
        """Administrator menu"""
        while True:
            clear_screen()
            print(f"\n=== ADMINISTRATOR MENU ===")
            print(f"Welcome, {self.current_user['username']}!")
            print("\n1. User Management")
            print("2. System Reports")
            print("3. Database Management")
            print("4. Export All Data")
            print("5. System Settings")
            print("6. Audit Logs")
            print("7. Financial Reports")
            print("8. Backup Database")
            print("9. Logout")
            
            choice = input("\nEnter your choice (1-9): ").strip()
            
            if choice == '1':
                self.user_management()
            elif choice == '2':
                self.system_reports()
            elif choice == '3':
                self.database_management()
            elif choice == '4':
                self.export_all_data()
            elif choice == '5':
                self.system_settings()
            elif choice == '6':
                self.audit_logs()
            elif choice == '7':
                self.financial_reports()
            elif choice == '8':
                self.backup_database()
            elif choice == '9':
                self.current_user = None
                return
            else:
                print("Invalid choice.")
                input("Press Enter to continue...")
    
    # ----- Admin menu implementations -----
    def user_management(self):
        while True:
            clear_screen()
            print("\n=== USER MANAGEMENT ===")
            print("1. List Users")
            print("2. Activate/Deactivate User")
            print("3. Reset User Password")
            print("4. Create Household User")
            print("5. Create Coordinator")
            print("6. Create Administrator")
            print("7. Back")
            choice = input("\nEnter choice (1-7): ").strip()
            if choice == '1':
                try:
                    conn = self.db.get_connection()
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT user_id, username, role, status, household_id, last_login
                        FROM users ORDER BY role, username
                    ''')
                    rows = cursor.fetchall()
                    conn.close()
                    print(f"\n{'ID':<5} {'Username':<20} {'Role':<12} {'Status':<10} {'HH':<5} {'Last Login':<19}")
                    print("-" * 75)
                    for r in rows:
                        last_login = r[5][:19] if r[5] else '—'
                        print(f"{r[0]:<5} {r[1]:<20} {r[2]:<12} {r[3]:<10} {str(r[4] or ''):<5} {last_login:<19}")
                except Exception as e:
                    print(f"Error listing users: {e}")
                input("Press Enter to continue...")
            elif choice == '2':
                try:
                    user_id = int(input("User ID: ").strip())
                    new_status = input("Set status to (active/inactive/suspended): ").strip()
                    if new_status not in ['active', 'inactive', 'suspended']:
                        print("Invalid status.")
                    else:
                        conn = self.db.get_connection()
                        cursor = conn.cursor()
                        cursor.execute("UPDATE users SET status = ? WHERE user_id = ?", (new_status, user_id))
                        conn.commit()
                        conn.close()
                        print("Status updated.")
                except ValueError:
                    print("Invalid input.")
                except Exception as e:
                    print(f"Error updating status: {e}")
                input("Press Enter to continue...")
            elif choice == '3':
                try:
                    user_id = int(input("User ID: ").strip())
                    temp_password = secrets.token_urlsafe(8)
                    password_hash, salt = hash_password(temp_password)
                    conn = self.db.get_connection()
                    cursor = conn.cursor()
                    cursor.execute("UPDATE users SET password_hash = ?, salt = ? WHERE user_id = ?", (password_hash, salt, user_id))
                    conn.commit()
                    conn.close()
                    print(f"Temporary password: {temp_password}")
                except ValueError:
                    print("Invalid input.")
                except Exception as e:
                    print(f"Error resetting password: {e}")
                input("Press Enter to continue...")
            elif choice == '4':
                self.auth.register_user('household')
            elif choice == '5':
                self.auth.register_user('coordinator')
            elif choice == '6':
                self.auth.register_user('admin')
            elif choice == '7':
                return
            else:
                print("Invalid choice.")
                input("Press Enter to continue...")
    
    def system_reports(self):
        clear_screen()
        print("\n=== SYSTEM REPORTS ===")
        self.generate_reports()
    
    def database_management(self):
        while True:
            clear_screen()
            print("\n=== DATABASE MANAGEMENT ===")
            print("1. VACUUM")
            print("2. Integrity Check")
            print("3. REINDEX")
            print("4. Back")
            choice = input("\nEnter choice (1-4): ").strip()
            try:
                if choice == '1':
                    conn = self.db.get_connection()
                    cursor = conn.cursor()
                    cursor.execute("VACUUM")
                    conn.commit()
                    conn.close()
                    print("VACUUM completed.")
                elif choice == '2':
                    conn = self.db.get_connection()
                    cursor = conn.cursor()
                    cursor.execute("PRAGMA integrity_check;")
                    result = cursor.fetchone()
                    conn.close()
                    print(f"Integrity check: {result[0]}")
                elif choice == '3':
                    conn = self.db.get_connection()
                    cursor = conn.cursor()
                    cursor.execute("REINDEX")
                    conn.commit()
                    conn.close()
                    print("REINDEX completed.")
                elif choice == '4':
                    return
                else:
                    print("Invalid choice.")
            except Exception as e:
                print(f"Database operation failed: {e}")
            input("Press Enter to continue...")
    
    def export_all_data(self):
        # Quick path to export all common datasets
        try:
            self.export_bookings()
            self.export_households()
            self.export_financial()
            self.export_usage_stats()
        except Exception as e:
            print(f"Export-all failed: {e}")
        input("Press Enter to continue...")
    
    def system_settings(self):
        while True:
            clear_screen()
            print("\n=== SYSTEM SETTINGS ===")
            print("1. List Source Pricing")
            print("2. Update Source Price")
            print("3. Back")
            choice = input("\nEnter choice (1-3): ").strip()
            if choice == '1':
                try:
                    conn = self.db.get_connection()
                    cursor = conn.cursor()
                    cursor.execute("SELECT source_id, source_name, price_per_100L FROM water_sources ORDER BY source_name")
                    rows = cursor.fetchall()
                    conn.close()
                    print(f"\n{'ID':<5} {'Source':<22} {'Price/100L':<10}")
                    print("-" * 40)
                    for r in rows:
                        print(f"{r[0]:<5} {r[1]:<22} ${r[2]:.2f}")
                except Exception as e:
                    print(f"Error listing pricing: {e}")
                input("Press Enter to continue...")
            elif choice == '2':
                try:
                    source_id = int(input("Source ID: ").strip())
                    new_price = float(input("New price per 100L ($): ").strip())
                    conn = self.db.get_connection()
                    cursor = conn.cursor()
                    cursor.execute("UPDATE water_sources SET price_per_100L = ? WHERE source_id = ?", (new_price, source_id))
                    conn.commit()
                    conn.close()
                    print("Price updated.")
                except ValueError:
                    print("Invalid input.")
                except Exception as e:
                    print(f"Error updating price: {e}")
                input("Press Enter to continue...")
            elif choice == '3':
                return
            else:
                print("Invalid choice.")
                input("Press Enter to continue...")
    
    def audit_logs(self):
        clear_screen()
        print("\n=== AUDIT LOGS ===")
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT b.booking_id, b.booking_status, b.approval_date, h.family_name, ws.source_name, ts.slot_date
                FROM bookings b
                JOIN households h ON b.household_id = h.household_id
                JOIN time_slots ts ON b.slot_id = ts.slot_id
                JOIN water_sources ws ON ts.source_id = ws.source_id
                WHERE b.approval_date IS NOT NULL
                ORDER BY b.approval_date DESC
                LIMIT 20
            ''')
            rows = cursor.fetchall()
            conn.close()
            if rows:
                print(f"{'Booking':<8} {'Status':<10} {'When':<19} {'Family':<18} {'Source':<18} {'Date':<10}")
                print("-" * 90)
                for r in rows:
                    when = r[2][:19] if r[2] else '—'
                    print(f"{r[0]:<8} {r[1]:<10} {when:<19} {r[3]:<18} {r[4]:<18} {r[5]:<10}")
            else:
                print("No recent approval/denial events.")
        except Exception as e:
            print(f"Error fetching audit logs: {e}")
        input("Press Enter to continue...")
    
    def financial_reports(self):
        clear_screen()
        print("\n=== FINANCIAL REPORTS ===")
        try:
            start_date = input("Start date (YYYY-MM-DD) [30 days ago]: ").strip()
            end_date = input("End date (YYYY-MM-DD) [today]: ").strip()
            if not end_date:
                end_date = datetime.now().strftime('%Y-%m-%d')
            if not start_date:
                start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
            conn = self.db.get_connection()
            cursor = conn.cursor()
            # Revenue by date
            cursor.execute('''
                SELECT ts.slot_date, SUM(b.amount_charged) as revenue
                FROM bookings b
                JOIN time_slots ts ON b.slot_id = ts.slot_id
                WHERE ts.slot_date BETWEEN ? AND ? AND b.booking_status = 'approved'
                GROUP BY ts.slot_date ORDER BY ts.slot_date
            ''', (start_date, end_date))
            by_date = cursor.fetchall()
            # Revenue by source
            cursor.execute('''
                SELECT ws.source_name, SUM(b.amount_charged) as revenue
                FROM bookings b
                JOIN time_slots ts ON b.slot_id = ts.slot_id
                JOIN water_sources ws ON ts.source_id = ws.source_id
                WHERE ts.slot_date BETWEEN ? AND ? AND b.booking_status = 'approved'
                GROUP BY ws.source_id, ws.source_name
                ORDER BY revenue DESC
            ''', (start_date, end_date))
            by_source = cursor.fetchall()
            conn.close()
            print(f"\nPeriod: {start_date} to {end_date}")
            if by_date:
                print("\n-- Revenue by Date --")
                print(f"{'Date':<12} {'Revenue':<10}")
                print("-" * 24)
                for r in by_date:
                    print(f"{r[0]:<12} ${r[1] or 0:.2f}")
            if by_source:
                print("\n-- Revenue by Source --")
                print(f"{'Source':<20} {'Revenue':<10}")
                print("-" * 32)
                for r in by_source:
                    print(f"{r[0]:<20} ${r[1] or 0:.2f}")
        except Exception as e:
            print(f"Error generating financial report: {e}")
        input("Press Enter to continue...")
    
    def backup_database(self):
        clear_screen()
        print("\n=== BACKUP DATABASE ===")
        try:
            import shutil
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_dir = 'backups'
            if not os.path.exists(backup_dir):
                os.makedirs(backup_dir)
            shutil.copy2(self.db.db_path, os.path.join(backup_dir, f"water_scheduler_{timestamp}.db"))
            print("Backup completed.")
        except Exception as e:
            print(f"Backup failed: {e}")
        input("Press Enter to continue...")
    
    def get_household_balance(self):
        """Get household account balance"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT balance FROM households WHERE household_id = ?", 
                          (self.current_user['household_id'],))
            result = cursor.fetchone()
            conn.close()
            return result[0] if result else 0.00
        except:
            return 0.00
    
    def make_booking(self):
        """Make water collection booking with improved date selection"""
        clear_screen()
        print("\n=== MAKE WATER COLLECTION BOOKING ===")
        
        # Show next 7 days as options
        print("Available dates for booking:")
        dates = []
        for i in range(7):
            date = (datetime.now() + timedelta(days=i)).strftime('%Y-%m-%d')
            day_name = (datetime.now() + timedelta(days=i)).strftime('%A')
            dates.append(date)
            print(f"{i+1}. {date} ({day_name})")
        
        try:
            choice = int(input("\nSelect date (1-7): ")) - 1
            if choice < 0 or choice >= 7:
                print("Invalid selection.")
                input("Press Enter to continue...")
                return
            
            selected_date = dates[choice]
            
        except ValueError:
            print("Invalid input.")
            input("Press Enter to continue...")
            return
        
        # Show available slots for selected date
        available_slots = self.get_available_slots(selected_date)
        
        if not available_slots:
            print(f"No available time slots found for {selected_date}.")
            input("Press Enter to continue...")
            return
        
        print(f"\nAvailable slots for {selected_date}:")
        print(f"{'#':<3} {'Source':<20} {'Time':<15} {'Price/100L':<12} {'Available':<10}")
        print("-" * 65)
        
        for i, slot in enumerate(available_slots):
            time_range = f"{slot[3]}-{slot[4]}"
            available_count = slot[6] - slot[5]
            price = f"${slot[8]:.2f}"
            print(f"{i+1:<3} {slot[1]:<20} {time_range:<15} {price:<12} {available_count:<10}")
        
        try:
            slot_choice = int(input(f"\nSelect slot (1-{len(available_slots)}): ")) - 1
            if slot_choice < 0 or slot_choice >= len(available_slots):
                print("Invalid selection.")
                input("Press Enter to continue...")
                return
            
            selected_slot = available_slots[slot_choice]
            slot_id = selected_slot[0]
            
            # Estimate cost
            water_amount = int(input("Estimated water amount (liters): "))
            cost = (water_amount / 100) * selected_slot[8]
            
            print(f"\nBooking Summary:")
            print(f"Date: {selected_date}")
            print(f"Source: {selected_slot[1]}")
            print(f"Time: {selected_slot[3]}-{selected_slot[4]}")
            print(f"Estimated cost: ${cost:.2f}")

            # Payment method selection
            # Payment method: only two options
            while True:
                print("\nBefore Confirming booking, Payment Options:")
                print("1. Mobile Payment")
                print("2. Cash Payment")
                pm_choice = input("Select payment method (1-2): ").strip()
                if pm_choice == '1':
                    payment_method = 'mobile'
                    print("Mobile payment selected.")
                    break
                if pm_choice == '2':
                    payment_method = 'cash'
                    print("Cash payment selected.")
                    break
                print("Invalid selection. Please choose 1 or 2.")

            confirm = input("\nConfirm booking? (y/n): ").lower()
            if confirm == 'y':
                booking_id = self.create_booking(slot_id, water_amount, cost, payment_method)
                if booking_id:
                    print(f"\nBooking request submitted! Booking ID: {booking_id}")
                    print("Your booking is pending approval.")
                else:
                    print("Booking failed.")
            
        except ValueError:
            print("Invalid input.")
        
        input("Press Enter to continue...")
    
    def get_available_slots(self, date):
        """Get available time slots for a date"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            # Get household priority
            cursor.execute("SELECT priority_level FROM households WHERE household_id = ?",
                          (self.current_user['household_id'],))
            priority = cursor.fetchone()[0]
            
            cursor.execute('''
                SELECT ts.slot_id, ws.source_name, ts.slot_date, ts.start_time, ts.end_time,
                       ts.current_bookings, ts.max_households, ws.location, ws.price_per_100L,
                       ws.priority_access
                FROM time_slots ts
                JOIN water_sources ws ON ts.source_id = ws.source_id
                WHERE ts.slot_date = ? AND ts.status = 'available' 
                AND ts.current_bookings < ts.max_households
                AND ws.status = 'active'
                AND (ws.priority_access = 'all' OR ws.priority_access LIKE ?)
                ORDER BY ws.source_name, ts.start_time
            ''', (date, f'%{priority}%'))
            
            slots = cursor.fetchall()
            conn.close()
            return slots
            
        except Exception as e:
            print(f"Error getting available slots: {e}")
            return []
    
    def create_booking(self, slot_id, water_amount, estimated_cost, payment_method):
        """Create new booking"""
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                conn = self.db.get_connection()
                cursor = conn.cursor()
                cursor.execute('BEGIN IMMEDIATE')
                cursor.execute('''
                    INSERT INTO bookings (household_id, slot_id, water_amount_collected, amount_charged, payment_method)
                    VALUES (?, ?, ?, ?, ?)
                ''', (self.current_user['household_id'], slot_id, water_amount, estimated_cost, payment_method))
                booking_id = cursor.lastrowid
                receipt_number = f"WS{datetime.now().strftime('%Y%m%d')}{booking_id:04d}"
                cursor.execute("UPDATE bookings SET receipt_number = ? WHERE booking_id = ?",
                              (receipt_number, booking_id))
                conn.commit()
                conn.close()
                return booking_id
            except sqlite3.OperationalError as e:
                # Handle database is locked with retries
                if 'database is locked' in str(e).lower() and attempt < max_attempts:
                    try:
                        conn.rollback()
                        conn.close()
                    except Exception:
                        pass
                    time.sleep(0.5 * attempt)
                    continue
                print(f"Database error creating booking: {e}")
                try:
                    conn.close()
                except Exception:
                    pass
                return None
            except sqlite3.IntegrityError as e:
                if 'UNIQUE constraint failed: bookings.household_id, bookings.slot_id' in str(e):
                    print("You already have a booking for this time slot.")
                else:
                    print(f"Database error creating booking: {e}")
                try:
                    conn.close()
                except Exception:
                    pass
                return None
            except Exception as e:
                print(f"Error creating booking: {e}")
                try:
                    conn.close()
                except Exception:
                    pass
                return None
    
    def view_my_bookings(self):
        """View household bookings with status"""
        clear_screen()
        print("\n=== MY BOOKINGS ===")
        
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT b.booking_id, ws.source_name, ts.slot_date, ts.start_time, ts.end_time,
                       b.booking_status, b.collection_status, b.amount_charged, b.receipt_number
                FROM bookings b
                JOIN time_slots ts ON b.slot_id = ts.slot_id
                JOIN water_sources ws ON ts.source_id = ws.source_id
                WHERE b.household_id = ?
                ORDER BY ts.slot_date DESC, ts.start_time DESC
                LIMIT 20
            ''', (self.current_user['household_id'],))
            
            bookings = cursor.fetchall()
            conn.close()
            
            if bookings:
                print(f"{'ID':<6} {'Source':<18} {'Date':<12} {'Time':<12} {'Status':<12} {'Cost':<8} {'Receipt':<12}")
                print("-" * 85)
                
                for booking in bookings:
                    time_range = f"{booking[3]}-{booking[4]}"
                    cost = f"${booking[7]:.2f}" if booking[7] else "N/A"
                    receipt = booking[8] or "N/A"
                    print(f"{booking[0]:<6} {booking[1]:<18} {booking[2]:<12} {time_range:<12} "
                          f"{booking[5]:<12} {cost:<8} {receipt:<12}")
            else:
                print("No bookings found.")
                
        except Exception as e:
            print(f"Error viewing bookings: {e}")
        
        input("Press Enter to continue...")
    
    def cancel_booking(self):
        """Cancel booking"""
        clear_screen()
        print("\n=== CANCEL BOOKING ===")
        
        try:
            booking_id = int(input("Enter Booking ID to cancel: "))
            
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT booking_status FROM bookings 
                WHERE booking_id = ? AND household_id = ?
            ''', (booking_id, self.current_user['household_id']))
            
            result = cursor.fetchone()
            if not result:
                print("Booking not found.")
                conn.close()
                input("Press Enter to continue...")
                return
            
            if result[0] not in ['pending', 'approved']:
                print("Cannot cancel this booking.")
                conn.close()
                input("Press Enter to continue...")
                return
            
            cursor.execute('''
                UPDATE bookings SET booking_status = 'cancelled' 
                WHERE booking_id = ? AND household_id = ?
            ''', (booking_id, self.current_user['household_id']))
            
            conn.commit()
            conn.close()
            
            print("Booking cancelled successfully.")
            
        except ValueError:
            print("Invalid Booking ID.")
        except Exception as e:
            print(f"Error cancelling booking: {e}")
        
        input("Press Enter to continue...")
    
    def view_water_sources(self):
        """View available water sources"""
        clear_screen()
        print("\n=== AVAILABLE WATER SOURCES ===")
        
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT source_name, source_type, location, price_per_100L, 
                       operating_start_time, operating_end_time, priority_access
                FROM water_sources 
                WHERE status = 'active'
                ORDER BY source_name
            ''')
            
            sources = cursor.fetchall()
            conn.close()
            
            if sources:
                print(f"{'Source':<20} {'Type':<10} {'Location':<25} {'Price/100L':<12} {'Hours':<15} {'Access':<15}")
                print("-" * 100)
                
                for source in sources:
                    hours = f"{source[4]}-{source[5]}"
                    price = f"${source[3]:.2f}"
                    access = source[6] or "All"
                    print(f"{source[0]:<20} {source[1]:<10} {source[2]:<25} {price:<12} {hours:<15} {access:<15}")
            else:
                print("No active water sources found.")
                
        except Exception as e:
            print(f"Error viewing water sources: {e}")
        
        input("Press Enter to continue...")
    
    def view_receipts(self):
        """View receipts"""
        clear_screen()
        print("\n=== MY RECEIPTS ===")
        
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT r.receipt_number, r.amount, r.water_amount, r.issue_date,
                       ws.source_name, ts.slot_date
                FROM receipts r
                JOIN bookings b ON r.booking_id = b.booking_id
                JOIN time_slots ts ON b.slot_id = ts.slot_id
                JOIN water_sources ws ON ts.source_id = ws.source_id
                WHERE r.household_id = ?
                ORDER BY r.issue_date DESC
                LIMIT 20
            ''', (self.current_user['household_id'],))
            
            receipts = cursor.fetchall()
            conn.close()
            
            if receipts:
                print(f"{'Receipt#':<15} {'Amount':<10} {'Water(L)':<10} {'Date':<12} {'Source':<20} {'Collection Date':<15}")
                print("-" * 85)
                
                for receipt in receipts:
                    amount = f"${receipt[1]:.2f}"
                    issue_date = receipt[3][:10] if receipt[3] else "N/A"
                    print(f"{receipt[0]:<15} {amount:<10} {receipt[2]:<10} {issue_date:<12} "
                          f"{receipt[4]:<20} {receipt[5]:<15}")
            else:
                print("No receipts found.")
                
        except Exception as e:
            print(f"Error viewing receipts: {e}")
        
        input("Press Enter to continue...")
    
    def add_funds(self):
        """Add funds to account"""
        clear_screen()
        print("\n=== ADD FUNDS TO ACCOUNT ===")
        
        current_balance = self.get_household_balance()
        print(f"Current balance: ${current_balance:.2f}")
        
        try:
            amount = float(input("Enter amount to add: $"))
            if amount <= 0:
                print("Amount must be positive.")
                input("Press Enter to continue...")
                return
            
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE households SET balance = balance + ? WHERE household_id = ?
            ''', (amount, self.current_user['household_id']))
            
            conn.commit()
            conn.close()
            
            new_balance = self.get_household_balance()
            print(f"Funds added successfully!")
            print(f"New balance: ${new_balance:.2f}")
            
        except ValueError:
            print("Invalid amount.")
        except Exception as e:
            print(f"Error adding funds: {e}")
        
        input("Press Enter to continue...")
    
    def view_notifications(self):
        """View notifications"""
        clear_screen()
        print("\n=== NOTIFICATIONS ===")
        
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT title, message, notification_type, created_date, is_read
                FROM notifications 
                WHERE user_id = ?
                ORDER BY created_date DESC
                LIMIT 10
            ''', (self.current_user['user_id'],))
            
            notifications = cursor.fetchall()
            
            if notifications:
                for i, notif in enumerate(notifications, 1):
                    status = "READ" if notif[4] else "NEW"
                    date = notif[3][:16] if notif[3] else "N/A"
                    print(f"{i}. [{status}] {notif[0]} - {date}")
                    print(f"   {notif[1]}")
                    print(f"   Type: {notif[2]}\n")
                
                # Mark as read
                cursor.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?",
                              (self.current_user['user_id'],))
                conn.commit()
            else:
                print("No notifications found.")
            
            conn.close()
            
        except Exception as e:
            print(f"Error viewing notifications: {e}")
        
        input("Press Enter to continue...")
    
    def update_profile(self):
        """Update household profile"""
        clear_screen()
        print("\n=== UPDATE PROFILE ===")
        
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT family_name, contact_phone, family_size, address
                FROM households WHERE household_id = ?
            ''', (self.current_user['household_id'],))
            
            current = cursor.fetchone()
            if not current:
                print("Profile not found.")
                conn.close()
                input("Press Enter to continue...")
                return
            
            print(f"Current family name: {current[0]}")
            new_name = input("New family name (press Enter to keep current): ").strip()
            if not new_name:
                new_name = current[0]
            
            print(f"Current phone: {current[1]}")
            new_phone = input("New phone (press Enter to keep current): ").strip()
            if not new_phone:
                new_phone = current[1]
            
            print(f"Current family size: {current[2]}")
            size_input = input("New family size (press Enter to keep current): ").strip()
            if size_input:
                try:
                    new_size = int(size_input)
                    if new_size <= 0:
                        print("Invalid family size.")
                        conn.close()
                        input("Press Enter to continue...")
                        return
                except ValueError:
                    print("Invalid family size.")
                    conn.close()
                    input("Press Enter to continue...")
                    return
            else:
                new_size = current[2]
            
            print(f"Current address: {current[3]}")
            new_address = input("New address (press Enter to keep current): ").strip()
            if not new_address:
                new_address = current[3]
            
            cursor.execute('''
                UPDATE households 
                SET family_name = ?, contact_phone = ?, family_size = ?, address = ?
                WHERE household_id = ?
            ''', (new_name, new_phone, new_size, new_address, self.current_user['household_id']))
            
            conn.commit()
            conn.close()
            
            print("Profile updated successfully!")
            
        except Exception as e:
            print(f"Error updating profile: {e}")
        
        input("Press Enter to continue...")
    
    def review_bookings(self):
        """Review and approve/deny booking requests"""
        clear_screen()
        print("\n=== REVIEW BOOKING REQUESTS ===")
        
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT b.booking_id, h.family_name, ws.source_name, ts.slot_date,
                       ts.start_time, ts.end_time, b.water_amount_collected, b.amount_charged,
                       h.priority_level, h.balance
                FROM bookings b
                JOIN households h ON b.household_id = h.household_id
                JOIN time_slots ts ON b.slot_id = ts.slot_id
                JOIN water_sources ws ON ts.source_id = ws.source_id
                WHERE b.booking_status = 'pending'
                ORDER BY ts.slot_date, ts.start_time
            ''')
            
            pending_bookings = cursor.fetchall()
            
            if not pending_bookings:
                print("No pending booking requests.")
                conn.close()
                input("Press Enter to continue...")
                return
            
            print(f"{'ID':<6} {'Family':<18} {'Source':<18} {'Date':<12} {'Time':<12} {'Priority':<10} {'Cost':<8}")
            print("-" * 90)
            
            for booking in pending_bookings:
                time_range = f"{booking[4]}-{booking[5]}"
                cost = f"${booking[7]:.2f}" if booking[7] else "N/A"
                print(f"{booking[0]:<6} {booking[1]:<18} {booking[2]:<18} {booking[3]:<12} "
                      f"{time_range:<12} {booking[8]:<10} {cost:<8}")
            
            try:
                booking_id = int(input("\nEnter Booking ID to review: "))
                action = input("Action (approve/deny): ").lower()
                
                if action not in ['approve', 'deny']:
                    print("Invalid action.")
                    conn.close()
                    input("Press Enter to continue...")
                    return
                
                new_status = 'approved' if action == 'approve' else 'denied'
                
                cursor.execute('''
                    UPDATE bookings 
                    SET booking_status = ?, approval_date = ?
                    WHERE booking_id = ?
                ''', (new_status, datetime.now().isoformat(' '), booking_id))
                
                # Update slot bookings count if approved
                if action == 'approve':
                    cursor.execute('''
                        UPDATE time_slots 
                        SET current_bookings = current_bookings + 1
                        WHERE slot_id = (SELECT slot_id FROM bookings WHERE booking_id = ?)
                    ''', (booking_id,))
                    # Create receipt if missing
                    cursor.execute('''
                        SELECT b.household_id, b.amount_charged, b.water_amount_collected, b.receipt_number, b.payment_method
                        FROM bookings b
                        WHERE b.booking_id = ?
                    ''', (booking_id,))
                    rec = cursor.fetchone()
                    if rec:
                        household_id, amount, water_amount, receipt_number, payment_method = rec
                        # Deduct funds only for mobile payments (cash handled offline)
                        if (payment_method or 'cash') == 'mobile':
                            cursor.execute('''
                                UPDATE households
                                SET balance = balance - ?
                                WHERE household_id = ?
                            ''', (amount or 0.0, household_id))
                        if not receipt_number:
                            receipt_number = f"WS{datetime.now().strftime('%Y%m%d')}{booking_id:04d}"
                            cursor.execute("UPDATE bookings SET receipt_number = ? WHERE booking_id = ?", (receipt_number, booking_id))
                        cursor.execute('''
                            INSERT OR IGNORE INTO receipts (receipt_number, household_id, booking_id, amount, water_amount, payment_method)
                            VALUES (?, ?, ?, ?, ?, ?)
                        ''', (receipt_number, household_id, booking_id, amount or 0.0, water_amount or 0, (payment_method or 'account_balance')))
                
                # Create notification
                cursor.execute("SELECT household_id FROM bookings WHERE booking_id = ?", (booking_id,))
                household_id = cursor.fetchone()[0]
                
                cursor.execute("SELECT user_id FROM users WHERE household_id = ?", (household_id,))
                user_result = cursor.fetchone()
                
                if user_result:
                    message = f"Your booking request #{booking_id} has been {new_status}."
                    cursor.execute('''
                        INSERT INTO notifications (user_id, household_id, title, message, notification_type)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (user_result[0], household_id, f"Booking {new_status.title()}", message, 'booking_update'))
                
                conn.commit()
                conn.close()
                
                print(f"Booking {new_status} successfully!")
                
            except ValueError:
                print("Invalid Booking ID.")
            
        except Exception as e:
            print(f"Error reviewing bookings: {e}")
        
        input("Press Enter to continue...")
    
    def generate_time_slots(self):
        """Generate time slots for water sources"""
        clear_screen()
        print("\n=== GENERATE TIME SLOTS ===")
        
        try:
            # Show water sources
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT source_id, source_name, operating_start_time, operating_end_time, capacity_per_hour
                FROM water_sources WHERE status = 'active'
                ORDER BY source_name
            ''')
            
            sources = cursor.fetchall()
            
            if not sources:
                print("No active water sources found.")
                conn.close()
                input("Press Enter to continue...")
                return
            
            print("Available water sources:")
            for i, source in enumerate(sources, 1):
                print(f"{i}. {source[1]} (Capacity: {source[4]}/hour)")
            
            try:
                choice = int(input(f"\nSelect source (1-{len(sources)}): ")) - 1
                if choice < 0 or choice >= len(sources):
                    print("Invalid selection.")
                    conn.close()
                    input("Press Enter to continue...")
                    return
                
                selected_source = sources[choice]
                source_id = selected_source[0]
                
                # Get date
                date_input = input("Enter date (YYYY-MM-DD) or press Enter for tomorrow: ").strip()
                if not date_input:
                    target_date = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
                else:
                    try:
                        datetime.strptime(date_input, '%Y-%m-%d')
                        target_date = date_input
                    except ValueError:
                        print("Invalid date format.")
                        conn.close()
                        input("Press Enter to continue...")
                        return
                
                # Generate slots
                start_time = datetime.strptime(selected_source[2], '%H:%M').time()
                end_time = datetime.strptime(selected_source[3], '%H:%M').time()
                capacity = selected_source[4]
                
                current_time = datetime.combine(datetime.strptime(target_date, '%Y-%m-%d').date(), start_time)
                end_datetime = datetime.combine(datetime.strptime(target_date, '%Y-%m-%d').date(), end_time)
                
                slots_created = 0
                while current_time < end_datetime:
                    slot_end = current_time + timedelta(minutes=60)  # 1-hour slots
                    
                    if slot_end.time() > end_time:
                        break
                    
                    cursor.execute('''
                        INSERT OR IGNORE INTO time_slots 
                        (source_id, slot_date, start_time, end_time, max_households)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (source_id, target_date, current_time.strftime('%H:%M'), 
                          slot_end.strftime('%H:%M'), capacity))
                    
                    if cursor.rowcount > 0:
                        slots_created += 1
                    
                    current_time = slot_end
                
                conn.commit()
                conn.close()
                
                print(f"Generated {slots_created} time slots for {selected_source[1]} on {target_date}")
                
            except ValueError:
                print("Invalid input.")
            
        except Exception as e:
            print(f"Error generating time slots: {e}")
        
        input("Press Enter to continue...")
    
    def generate_reports(self):
        """Generate various reports"""
        clear_screen()
        print("\n=== GENERATE REPORTS ===")
        print("1. Daily Usage Report")
        print("2. Revenue Report")
        print("3. Household Activity Report")
        print("4. Source Performance Report")
        
        choice = input("\nSelect report type (1-4): ").strip()
        
        if choice == '1':
            self.daily_usage_report()
        elif choice == '2':
            self.revenue_report()
        elif choice == '3':
            self.household_activity_report()
        elif choice == '4':
            self.source_performance_report()
        else:
            print("Invalid choice.")
        
        input("Press Enter to continue...")
    
    def daily_usage_report(self):
        """Generate daily usage report"""
        date = input("Enter date (YYYY-MM-DD) or press Enter for today: ").strip()
        if not date:
            date = datetime.now().strftime('%Y-%m-%d')
        
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT ws.source_name, COUNT(b.booking_id) as bookings,
                       SUM(b.water_amount_collected) as total_water,
                       SUM(b.amount_charged) as total_revenue
                FROM bookings b
                JOIN time_slots ts ON b.slot_id = ts.slot_id
                JOIN water_sources ws ON ts.source_id = ws.source_id
                WHERE ts.slot_date = ? AND b.booking_status = 'approved'
                GROUP BY ws.source_id, ws.source_name
                ORDER BY total_revenue DESC
            ''', (date,))
            
            results = cursor.fetchall()
            conn.close()
            
            print(f"\n=== DAILY USAGE REPORT - {date} ===")
            if results:
                print(f"{'Source':<20} {'Bookings':<10} {'Water(L)':<12} {'Revenue':<10}")
                print("-" * 55)
                
                total_bookings = 0
                total_water = 0
                total_revenue = 0
                
                for row in results:
                    water = row[2] or 0
                    revenue = row[3] or 0
                    total_bookings += row[1]
                    total_water += water
                    total_revenue += revenue
                    
                    print(f"{row[0]:<20} {row[1]:<10} {water:<12} ${revenue:<9.2f}")
                
                print("-" * 55)
                print(f"{'TOTAL':<20} {total_bookings:<10} {total_water:<12} ${total_revenue:<9.2f}")
            else:
                print("No data found for this date.")
                
        except Exception as e:
            print(f"Error generating report: {e}")
    
    def export_data(self):
        """Export data to CSV"""
        clear_screen()
        print("\n=== EXPORT DATA ===")
        print("1. Export All Bookings")
        print("2. Export Household Data")
        print("3. Export Financial Data")
        print("4. Export Usage Statistics")
        
        choice = input("\nSelect export type (1-4): ").strip()
        
        try:
            if choice == '1':
                self.export_bookings()
            elif choice == '2':
                self.export_households()
            elif choice == '3':
                self.export_financial()
            elif choice == '4':
                self.export_usage_stats()
            else:
                print("Invalid choice.")
                
        except Exception as e:
            print(f"Export failed: {e}")
        
        input("Press Enter to continue...")
    
    def export_bookings(self):
        """Export bookings to CSV"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT b.booking_id, h.family_name, ws.source_name, ts.slot_date,
                       ts.start_time, ts.end_time, b.booking_status, b.amount_charged,
                       b.water_amount_collected, b.receipt_number
                FROM bookings b
                JOIN households h ON b.household_id = h.household_id
                JOIN time_slots ts ON b.slot_id = ts.slot_id
                JOIN water_sources ws ON ts.source_id = ws.source_id
                ORDER BY ts.slot_date DESC
            ''')
            
            bookings = cursor.fetchall()
            conn.close()
            
            if not os.path.exists('exports'):
                os.makedirs('exports')
            
            filename = f"exports/bookings_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(['Booking ID', 'Family Name', 'Source', 'Date', 'Start Time', 
                               'End Time', 'Status', 'Amount Charged', 'Water Amount', 'Receipt Number'])
                writer.writerows(bookings)
            
            print(f"Bookings exported to: {filename}")
            
        except Exception as e:
            print(f"Error exporting bookings: {e}")
    
    def export_households(self):
        """Export households to CSV"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT household_id, family_name, contact_phone, contact_email, family_size,
                       priority_level, address, balance, status
                FROM households ORDER BY family_name
            ''')
            rows = cursor.fetchall()
            conn.close()
            if not os.path.exists('exports'):
                os.makedirs('exports')
            filename = f"exports/households_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(['Household ID', 'Family Name', 'Phone', 'Email', 'Family Size', 'Priority', 'Address', 'Balance', 'Status'])
                writer.writerows(rows)
            print(f"Households exported to: {filename}")
        except Exception as e:
            print(f"Error exporting households: {e}")
    
    def export_financial(self):
        """Export simple financial summary to CSV"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT ts.slot_date as date, SUM(b.amount_charged) as revenue
                FROM bookings b
                JOIN time_slots ts ON b.slot_id = ts.slot_id
                WHERE b.booking_status = 'approved'
                GROUP BY ts.slot_date ORDER BY ts.slot_date DESC
            ''')
            rows = cursor.fetchall()
            conn.close()
            if not os.path.exists('exports'):
                os.makedirs('exports')
            filename = f"exports/financial_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(['Date', 'Revenue'])
                for r in rows:
                    writer.writerow([r[0], f"{r[1] or 0:.2f}"])
            print(f"Financial data exported to: {filename}")
        except Exception as e:
            print(f"Error exporting financial data: {e}")
    
    def export_usage_stats(self):
        """Export usage statistics to CSV"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT ws.source_name, COUNT(b.booking_id) as bookings, SUM(b.water_amount_collected) as total_water
                FROM bookings b
                JOIN time_slots ts ON b.slot_id = ts.slot_id
                JOIN water_sources ws ON ts.source_id = ws.source_id
                WHERE b.booking_status = 'approved'
                GROUP BY ws.source_id, ws.source_name
                ORDER BY bookings DESC
            ''')
            rows = cursor.fetchall()
            conn.close()
            if not os.path.exists('exports'):
                os.makedirs('exports')
            filename = f"exports/usage_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(['Source', 'Bookings', 'Total Water (L)'])
                writer.writerows(rows)
            print(f"Usage stats exported to: {filename}")
        except Exception as e:
            print(f"Error exporting usage stats: {e}")
    
    def manage_water_sources(self):
        """Manage water sources"""
        while True:
            clear_screen()
            print("\n=== MANAGE WATER SOURCES ===")
            print("1. View All Sources")
            print("2. Add New Source")
            print("3. Update Source")
            print("4. Toggle Source Status")
            print("5. Back to Main Menu")
            
            choice = input("\nEnter choice (1-5): ").strip()
            
            if choice == '1':
                self.view_all_sources()
            elif choice == '2':
                self.add_water_source()
            elif choice == '3':
                self.update_water_source()
            elif choice == '4':
                self.toggle_source_status()
            elif choice == '5':
                break
            else:
                print("Invalid choice.")
                input("Press Enter to continue...")
    
    def view_all_sources(self):
        """View all water sources"""
        clear_screen()
        print("\n=== ALL WATER SOURCES ===")
        
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT source_id, source_name, source_type, location, capacity_per_hour,
                       operating_start_time, operating_end_time, status, price_per_100L
                FROM water_sources
                ORDER BY source_name
            ''')
            
            sources = cursor.fetchall()
            conn.close()
            
            if sources:
                print(f"{'ID':<4} {'Name':<20} {'Type':<10} {'Capacity':<10} {'Hours':<15} {'Price':<8} {'Status':<10}")
                print("-" * 80)
                
                for source in sources:
                    hours = f"{source[5]}-{source[6]}"
                    price = f"${source[8]:.2f}"
                    print(f"{source[0]:<4} {source[1]:<20} {source[2]:<10} {source[4]:<10} "
                          f"{hours:<15} {price:<8} {source[7]:<10}")
            else:
                print("No water sources found.")
                
        except Exception as e:
            print(f"Error viewing sources: {e}")
        
        input("Press Enter to continue...")
    
    def add_water_source(self):
        """Add new water source"""
        clear_screen()
        print("\n=== ADD NEW WATER SOURCE ===")
        
        try:
            name = input("Source name: ").strip()
            if not name:
                print("Name is required.")
                input("Press Enter to continue...")
                return
            
            print("Source types: 1=Well, 2=Borehole, 3=Tap, 4=Spring, 5=Tank")
            type_choice = input("Select type (1-5): ").strip()
            types = {'1': 'Well', '2': 'Borehole', '3': 'Tap', '4': 'Spring', '5': 'Tank'}
            source_type = types.get(type_choice)
            
            if not source_type:
                print("Invalid type selection.")
                input("Press Enter to continue...")
                return
            
            location = input("Location: ").strip()
            if not location:
                print("Location is required.")
                input("Press Enter to continue...")
                return
            
            capacity = int(input("Capacity per hour: "))
            start_time = input("Opening time (HH:MM): ").strip()
            end_time = input("Closing time (HH:MM): ").strip()
            price = float(input("Price per 100L ($): "))
            
            # Validate times
            datetime.strptime(start_time, '%H:%M')
            datetime.strptime(end_time, '%H:%M')
            
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO water_sources (source_name, source_type, location, capacity_per_hour,
                                         operating_start_time, operating_end_time, price_per_100L)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (name, source_type, location, capacity, start_time, end_time, price))
            
            source_id = cursor.lastrowid
            conn.commit()
            conn.close()
            
            print(f"Water source added successfully! ID: {source_id}")
            
        except ValueError:
            print("Invalid input format.")
        except Exception as e:
            print(f"Error adding source: {e}")
        
        input("Press Enter to continue...")
    
    def update_water_source(self):
        """Update an existing water source"""
        clear_screen()
        print("\n=== UPDATE WATER SOURCE ===")
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            # List sources
            cursor.execute('''
                SELECT source_id, source_name, source_type, location, capacity_per_hour,
                       operating_start_time, operating_end_time, status, price_per_100L
                FROM water_sources
                ORDER BY source_name
            ''')
            sources = cursor.fetchall()
            if not sources:
                conn.close()
                print("No water sources found.")
                input("Press Enter to continue...")
                return
            print(f"{'ID':<4} {'Name':<20} {'Type':<10} {'Capacity':<10} {'Hours':<15} {'Price':<8} {'Status':<10}")
            print("-" * 80)
            for s in sources:
                hours = f"{s[5]}-{s[6]}"
                price = f"${s[8]:.2f}"
                print(f"{s[0]:<4} {s[1]:<20} {s[2]:<10} {s[4]:<10} {hours:<15} {price:<8} {s[7]:<10}")
            try:
                source_id = int(input("\nEnter Source ID to update: ").strip())
            except ValueError:
                conn.close()
                print("Invalid Source ID.")
                input("Press Enter to continue...")
                return
            cursor.execute('''
                SELECT source_name, source_type, location, capacity_per_hour,
                       operating_start_time, operating_end_time, status, price_per_100L
                FROM water_sources WHERE source_id = ?
            ''', (source_id,))
            cur = cursor.fetchone()
            if not cur:
                conn.close()
                print("Source not found.")
                input("Press Enter to continue...")
                return
            print(f"\nCurrent name: {cur[0]}")
            new_name = input("New name (Enter to keep): ").strip() or cur[0]
            print(f"Current type: {cur[1]} (choices: Well/Borehole/Tap/Spring/Tank)")
            new_type = input("New type (Enter to keep): ").strip() or cur[1]
            if new_type not in ['Well', 'Borehole', 'Tap', 'Spring', 'Tank']:
                new_type = cur[1]
            print(f"Current location: {cur[2]}")
            new_location = input("New location (Enter to keep): ").strip() or cur[2]
            print(f"Current capacity/hour: {cur[3]}")
            cap_in = input("New capacity/hour (Enter to keep): ").strip()
            if cap_in:
                try:
                    new_capacity = int(cap_in)
                    if new_capacity <= 0:
                        print("Invalid capacity; keeping current.")
                        new_capacity = cur[3]
                except ValueError:
                    print("Invalid capacity; keeping current.")
                    new_capacity = cur[3]
            else:
                new_capacity = cur[3]
            print(f"Current opening time (HH:MM): {cur[4]}")
            start_in = input("New opening time (HH:MM, Enter to keep): ").strip()
            if start_in:
                try:
                    datetime.strptime(start_in, '%H:%M')
                    new_start = start_in
                except ValueError:
                    print("Invalid time; keeping current.")
                    new_start = cur[4]
            else:
                new_start = cur[4]
            print(f"Current closing time (HH:MM): {cur[5]}")
            end_in = input("New closing time (HH:MM, Enter to keep): ").strip()
            if end_in:
                try:
                    datetime.strptime(end_in, '%H:%M')
                    new_end = end_in
                except ValueError:
                    print("Invalid time; keeping current.")
                    new_end = cur[5]
            else:
                new_end = cur[5]
            # Ensure logical time ordering
            try:
                if datetime.strptime(new_end, '%H:%M') <= datetime.strptime(new_start, '%H:%M'):
                    print("Closing time must be after opening time; keeping current times.")
                    new_start, new_end = cur[4], cur[5]
            except Exception:
                new_start, new_end = cur[4], cur[5]
            print(f"Current price per 100L: ${cur[7]:.2f}")
            price_in = input("New price per 100L ($, Enter to keep): ").strip()
            if price_in:
                try:
                    new_price = float(price_in)
                except ValueError:
                    print("Invalid price; keeping current.")
                    new_price = cur[7]
            else:
                new_price = cur[7]
            print(f"Current status: {cur[6]} (active/inactive/maintenance)")
            status_in = input("New status (Enter to keep): ").strip().lower()
            if status_in in ['active', 'inactive', 'maintenance']:
                new_status = status_in
            else:
                new_status = cur[6]
            cursor.execute('''
                UPDATE water_sources
                SET source_name = ?, source_type = ?, location = ?, capacity_per_hour = ?,
                    operating_start_time = ?, operating_end_time = ?, status = ?, price_per_100L = ?
                WHERE source_id = ?
            ''', (new_name, new_type, new_location, new_capacity, new_start, new_end, new_status, new_price, source_id))
            conn.commit()
            conn.close()
            print("Water source updated successfully.")
        except Exception as e:
            print(f"Error updating water source: {e}")
        input("Press Enter to continue...")
    
    def toggle_source_status(self):
        """Toggle or set water source status"""
        clear_screen()
        print("\n=== TOGGLE SOURCE STATUS ===")
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            # List sources
            cursor.execute('''
                SELECT source_id, source_name, status
                FROM water_sources
                ORDER BY source_name
            ''')
            rows = cursor.fetchall()
            if not rows:
                conn.close()
                print("No water sources found.")
                input("Press Enter to continue...")
                return
            print(f"{'ID':<4} {'Name':<22} {'Status':<12}")
            print("-" * 40)
            for r in rows:
                print(f"{r[0]:<4} {r[1]:<22} {r[2]:<12}")
            try:
                source_id = int(input("\nEnter Source ID: ").strip())
            except ValueError:
                conn.close()
                print("Invalid Source ID.")
                input("Press Enter to continue...")
                return
            # Get current status
            cursor.execute("SELECT status FROM water_sources WHERE source_id = ?", (source_id,))
            row = cursor.fetchone()
            if not row:
                conn.close()
                print("Source not found.")
                input("Press Enter to continue...")
                return
            current_status = row[0]
            prompt = "Set status to (active/inactive/maintenance) [toggle]: "
            desired = input(prompt).strip().lower()
            valid_statuses = ['active', 'inactive', 'maintenance']
            if desired:
                if desired not in valid_statuses:
                    conn.close()
                    print("Invalid status.")
                    input("Press Enter to continue...")
                    return
                new_status = desired
            else:
                # Toggle behavior: active <-> inactive, maintenance -> active
                if current_status == 'active':
                    new_status = 'inactive'
                elif current_status == 'inactive':
                    new_status = 'active'
                else:
                    new_status = 'active'
            cursor.execute("UPDATE water_sources SET status = ? WHERE source_id = ?", (new_status, source_id))
            conn.commit()
            conn.close()
            print(f"Source status updated: {current_status} -> {new_status}")
        except Exception as e:
            print(f"Error updating source status: {e}")
        input("Press Enter to continue...")
    
    def view_daily_summary(self):
        """View daily summary"""
        clear_screen()
        date = input("Enter date (YYYY-MM-DD) or press Enter for today: ").strip()
        if not date:
            date = datetime.now().strftime('%Y-%m-%d')
        
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            # Get summary statistics
            cursor.execute('''
                SELECT 
                    COUNT(CASE WHEN b.booking_status = 'pending' THEN 1 END) as pending,
                    COUNT(CASE WHEN b.booking_status = 'approved' THEN 1 END) as approved,
                    COUNT(CASE WHEN b.collection_status = 'completed' THEN 1 END) as completed,
                    SUM(CASE WHEN b.booking_status = 'approved' THEN b.amount_charged ELSE 0 END) as revenue
                FROM bookings b
                JOIN time_slots ts ON b.slot_id = ts.slot_id
                WHERE ts.slot_date = ?
            ''', (date,))
            
            summary = cursor.fetchone()
            conn.close()
            
            print(f"\n=== DAILY SUMMARY - {date} ===")
            print(f"Pending Bookings: {summary[0] or 0}")
            print(f"Approved Bookings: {summary[1] or 0}")
            print(f"Completed Collections: {summary[2] or 0}")
            print(f"Total Revenue: ${summary[3] or 0:.2f}")
            
        except Exception as e:
            print(f"Error generating summary: {e}")
        
        input("Press Enter to continue...")
    
    def manage_households(self):
        """Manage households"""
        while True:
            clear_screen()
            print("\n=== MANAGE HOUSEHOLDS ===")
            print("1. View All Households")
            print("2. Add New Household")
            print("3. Update Household")
            print("4. Deactivate/Activate Household")
            print("5. View Household Details")
            print("6. Back to Main Menu")
            
            choice = input("\nEnter choice (1-6): ").strip()
            
            if choice == '1':
                self.view_all_households()
            elif choice == '2':
                self.add_household()
            elif choice == '3':
                self.update_household()
            elif choice == '4':
                self.toggle_household_status()
            elif choice == '5':
                self.view_household_details()
            elif choice == '6':
                break
            else:
                print("Invalid choice.")
                input("Press Enter to continue...")
    
    def view_all_households(self):
        """View all households"""
        clear_screen()
        print("\n=== ALL HOUSEHOLDS ===")
        
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT household_id, family_name, contact_phone, contact_email, 
                       family_size, priority_level, address, balance, status
                FROM households
                ORDER BY family_name
            ''')
            
            households = cursor.fetchall()
            conn.close()
            
            if households:
                print(f"{'ID':<4} {'Family Name':<20} {'Phone':<15} {'Size':<5} {'Priority':<10} {'Balance':<10} {'Status':<10}")
                print("-" * 90)
                
                for household in households:
                    balance = f"${household[7]:.2f}" if household[7] else "$0.00"
                    print(f"{household[0]:<4} {household[1]:<20} {household[2] or 'N/A':<15} "
                          f"{household[4]:<5} {household[5]:<10} {balance:<10} {household[8]:<10}")
            else:
                print("No households found.")
                
        except Exception as e:
            print(f"Error viewing households: {e}")
        
        input("Press Enter to continue...")
    
    def add_household(self):
        """Add new household"""
        clear_screen()
        print("\n=== ADD NEW HOUSEHOLD ===")
        
        try:
            family_name = input("Family name: ").strip()
            if not family_name:
                print("Family name is required.")
                input("Press Enter to continue...")
                return
            
            contact_phone = input("Contact phone: ").strip()
            contact_email = input("Contact email: ").strip()
            
            family_size = int(input("Family size: "))
            if family_size <= 0:
                print("Family size must be greater than 0.")
                input("Press Enter to continue...")
                return
            
            priority_level = input("Priority level (high/normal/low) [normal]: ").strip() or 'normal'
            if priority_level not in ['high', 'normal', 'low']:
                priority_level = 'normal'
            
            address = input("Address: ").strip()
            balance = float(input("Initial balance ($) [50.00]: ").strip() or "50.00")
            
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO households (family_name, contact_phone, contact_email, 
                                      family_size, priority_level, address, balance)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (family_name, contact_phone, contact_email, family_size, 
                  priority_level, address, balance))
            
            household_id = cursor.lastrowid
            
            # Create user account for household
            username = family_name.lower().replace(' ', '_')
            password, salt = hash_password("password123")
            cursor.execute('''
                INSERT INTO users (username, email, password_hash, salt, role, household_id, is_verified)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (username, contact_email or f"{username}@watersystem.local", 
                  password, salt, "household", household_id, True))
            
            conn.commit()
            conn.close()
            
            print(f"Household added successfully! ID: {household_id}")
            print(f"Username: {username}")
            print(f"Password: password123")
            
        except ValueError:
            print("Invalid input format.")
        except Exception as e:
            print(f"Error adding household: {e}")
        
        input("Press Enter to continue...")
    
    def update_household(self):
        """Update household information"""
        clear_screen()
        print("\n=== UPDATE HOUSEHOLD ===")
        
        try:
            household_id = int(input("Enter Household ID: "))
            
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT family_name, contact_phone, contact_email, family_size, 
                       priority_level, address, balance
                FROM households WHERE household_id = ?
            ''', (household_id,))
            
            current = cursor.fetchone()
            if not current:
                print("Household not found.")
                conn.close()
                input("Press Enter to continue...")
                return
            
            print(f"Current family name: {current[0]}")
            new_name = input("New family name (press Enter to keep current): ").strip()
            if not new_name:
                new_name = current[0]
            
            print(f"Current phone: {current[1]}")
            new_phone = input("New phone (press Enter to keep current): ").strip()
            if not new_phone:
                new_phone = current[1]
            
            print(f"Current email: {current[2]}")
            new_email = input("New email (press Enter to keep current): ").strip()
            if not new_email:
                new_email = current[2]
            
            print(f"Current family size: {current[3]}")
            size_input = input("New family size (press Enter to keep current): ").strip()
            if size_input:
                try:
                    new_size = int(size_input)
                    if new_size <= 0:
                        print("Invalid family size.")
                        conn.close()
                        input("Press Enter to continue...")
                        return
                except ValueError:
                    print("Invalid family size.")
                    conn.close()
                    input("Press Enter to continue...")
                    return
            else:
                new_size = current[3]
            
            print(f"Current priority: {current[4]}")
            priority_input = input("New priority (high/normal/low, press Enter to keep current): ").strip()
            if priority_input and priority_input in ['high', 'normal', 'low']:
                new_priority = priority_input
            else:
                new_priority = current[4]
            
            print(f"Current address: {current[5]}")
            new_address = input("New address (press Enter to keep current): ").strip()
            if not new_address:
                new_address = current[5]
            
            print(f"Current balance: ${current[6]:.2f}")
            balance_input = input("New balance (press Enter to keep current): ").strip()
            if balance_input:
                try:
                    new_balance = float(balance_input)
                except ValueError:
                    print("Invalid balance.")
                    conn.close()
                    input("Press Enter to continue...")
                    return
            else:
                new_balance = current[6]
            
            cursor.execute('''
                UPDATE households 
                SET family_name = ?, contact_phone = ?, contact_email = ?, 
                    family_size = ?, priority_level = ?, address = ?, balance = ?
                WHERE household_id = ?
            ''', (new_name, new_phone, new_email, new_size, new_priority, 
                  new_address, new_balance, household_id))
            
            conn.commit()
            conn.close()
            
            print("Household updated successfully!")
            
        except ValueError:
            print("Invalid Household ID.")
        except Exception as e:
            print(f"Error updating household: {e}")
        
        input("Press Enter to continue...")
    
    def send_notifications(self):
        """Send notifications to households"""
        clear_screen()
        print("\n=== SEND NOTIFICATIONS ===")
        
        while True:
            print("\n1. Send Individual Notification")
            print("2. Send Group Notification")
            print("3. Back to Main Menu")
            
            choice = input("\nEnter choice (1-3): ").strip()
            
            if choice == '1':
                try:
                    # Get household ID
                    household_id = int(input("Enter Household ID: ").strip())
                    
                    # Verify household exists and get user_id
                    conn = self.db.get_connection()
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT users.user_id, households.family_name 
                        FROM users 
                        JOIN households ON users.household_id = households.household_id 
                        WHERE households.household_id = ?
                    ''', (household_id,))
                    
                    result = cursor.fetchone()
                    if not result:
                        print("Household not found.")
                        conn.close()
                        input("Press Enter to continue...")
                        continue
                    
                    user_id, family_name = result
                    
                    # Get notification details
                    title = input("Notification title: ").strip()
                    message = input("Notification message: ").strip()
                    notification_type = input("Notification type (general/reminder/alert/warning): ").strip().lower()
                    
                    if not title or not message:
                        print("Title and message are required.")
                        conn.close()
                        input("Press Enter to continue...")
                        continue
                    
                    if notification_type not in ['general', 'reminder', 'alert', 'warning']:
                        notification_type = 'general'
                    
                    # Insert notification
                    cursor.execute('''
                        INSERT INTO notifications (user_id, household_id, title, message, notification_type)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (user_id, household_id, title, message, notification_type))
                    
                    conn.commit()
                    conn.close()
                    
                    print(f"Notification sent to {family_name}!")
                    
                except ValueError:
                    print("Invalid household ID.")
                except Exception as e:
                    print(f"Error sending notification: {e}")
                input("Press Enter to continue...")
                
            elif choice == '2':
                try:
                    print("\nSelect target group:")
                    print("1. All Households")
                    print("2. High Priority Households")
                    print("3. Normal Priority Households")
                    print("4. Low Priority Households")
                    print("5. Active Households")
                    print("6. Households with Low Balance")
                    
                    group_choice = input("\nEnter choice (1-6): ").strip()
                    
                    title = input("Notification title: ").strip()
                    message = input("Notification message: ").strip()
                    notification_type = input("Notification type (general/reminder/alert/warning): ").strip().lower()
                    
                    if not title or not message:
                        print("Title and message are required.")
                        input("Press Enter to continue...")
                        continue
                    
                    if notification_type not in ['general', 'reminder', 'alert', 'warning']:
                        notification_type = 'general'
                    
                    conn = self.db.get_connection()
                    cursor = conn.cursor()
                    
                    query = '''
                        SELECT users.user_id, households.household_id 
                        FROM users 
                        JOIN households ON users.household_id = households.household_id 
                        WHERE 1=1
                    '''
                    
                    if group_choice == '2':
                        query += " AND households.priority_level = 'high'"
                    elif group_choice == '3':
                        query += " AND households.priority_level = 'normal'"
                    elif group_choice == '4':
                        query += " AND households.priority_level = 'low'"
                    elif group_choice == '5':
                        query += " AND households.status = 'active'"
                    elif group_choice == '6':
                        query += " AND households.balance < 10.00"
                    
                    cursor.execute(query)
                    recipients = cursor.fetchall()
                    
                    if not recipients:
                        print("No matching households found.")
                        conn.close()
                        input("Press Enter to continue...")
                        continue
                    
                    # Insert notifications for all recipients
                    for user_id, household_id in recipients:
                        cursor.execute('''
                            INSERT INTO notifications (user_id, household_id, title, message, notification_type)
                            VALUES (?, ?, ?, ?, ?)
                        ''', (user_id, household_id, title, message, notification_type))
                    
                    conn.commit()
                    conn.close()
                    
                    print(f"Notification sent to {len(recipients)} households!")
                    
                except Exception as e:
                    print(f"Error sending group notification: {e}")
                input("Press Enter to continue...")
                
            elif choice == '3':
                break
            else:
                print("Invalid choice.")
                input("Press Enter to continue...")

    def toggle_household_status(self):
        """Toggle household active/inactive status"""
        clear_screen()
        print("\n=== TOGGLE HOUSEHOLD STATUS ===")
        
        try:
            household_id = int(input("Enter Household ID: "))
            new_status = input("Set status to (active/inactive/suspended): ").strip()
            
            if new_status not in ['active', 'inactive', 'suspended']:
                print("Invalid status.")
                input("Press Enter to continue...")
                return
            
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("UPDATE households SET status = ? WHERE household_id = ?", 
                          (new_status, household_id))
            
            if cursor.rowcount > 0:
                # Also update user status
                cursor.execute("UPDATE users SET status = ? WHERE household_id = ?", 
                              (new_status, household_id))
                conn.commit()
                print(f"Household status updated to {new_status}.")
            else:
                print("Household not found.")
            
            conn.close()
            
        except ValueError:
            print("Invalid Household ID.")
        except Exception as e:
            print(f"Error updating status: {e}")
        
        input("Press Enter to continue...")
    
    def view_household_details(self):
        """View detailed household information"""
        clear_screen()
        print("\n=== HOUSEHOLD DETAILS ===")
        
        try:
            household_id = int(input("Enter Household ID: "))
            
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT household_id, family_name, contact_phone, contact_email, 
                       family_size, priority_level, address, balance, status, 
                       registration_date
                FROM households WHERE household_id = ?
            ''', (household_id,))
            
            household = cursor.fetchone()
            if not household:
                print("Household not found.")
                conn.close()
                input("Press Enter to continue...")
                return
            
            print(f"\nHousehold ID: {household[0]}")
            print(f"Family Name: {household[1]}")
            print(f"Contact Phone: {household[2] or 'N/A'}")
            print(f"Contact Email: {household[3] or 'N/A'}")
            print(f"Family Size: {household[4]}")
            print(f"Priority Level: {household[5]}")
            print(f"Address: {household[6] or 'N/A'}")
            print(f"Balance: ${household[7]:.2f}")
            print(f"Status: {household[8]}")
            print(f"Registration Date: {household[9]}")
            
            # Show recent bookings
            cursor.execute('''
                SELECT b.booking_id, ws.source_name, ts.slot_date, ts.start_time, 
                       b.booking_status, b.amount_charged
                FROM bookings b
                JOIN time_slots ts ON b.slot_id = ts.slot_id
                JOIN water_sources ws ON ts.source_id = ws.source_id
                WHERE b.household_id = ?
                ORDER BY ts.slot_date DESC
                LIMIT 5
            ''', (household_id,))
            
            recent_bookings = cursor.fetchall()
            if recent_bookings:
                print(f"\nRecent Bookings:")
                print(f"{'ID':<6} {'Source':<18} {'Date':<12} {'Time':<12} {'Status':<12} {'Amount':<8}")
                print("-" * 70)
                for booking in recent_bookings:
                    time_range = f"{booking[3]}-{booking[4]}" if booking[4] else "N/A"
                    amount = f"${booking[5]:.2f}" if booking[5] else "N/A"
                    print(f"{booking[0]:<6} {booking[1]:<18} {booking[2]:<12} {time_range:<12} "
                          f"{booking[4]:<12} {amount:<8}")
            else:
                print("\nNo recent bookings found.")
            
            conn.close()
            
        except ValueError:
            print("Invalid Household ID.")
        except Exception as e:
            print(f"Error viewing household details: {e}")
        
        input("Press Enter to continue...")
    
    def run(self):
        """Main application loop"""
        self.main_menu()

def main():
    """Entry point"""
    try:
        app = WaterSchedulerApp()
        app.run()
    except KeyboardInterrupt:
        print("\n\nSystem interrupted by user. Goodbye!")
    except Exception as e:
        print(f"\nUnexpected error: {e}")

if __name__ == "__main__":
    main()
