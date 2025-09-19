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
            
            confirm = input("\nConfirm booking? (y/n): ").lower()
            if confirm == 'y':
                booking_id = self.create_booking(slot_id, water_amount, cost)
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
    
    def create_booking(self, slot_id, water_amount, estimated_cost):
        """Create new booking"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO bookings (household_id, slot_id, water_amount_collected, amount_charged)
                VALUES (?, ?, ?, ?)
            ''', (self.current_user['household_id'], slot_id, water_amount, estimated_cost))
            
            booking_id = cursor.lastrowid
            receipt_number = f"WS{datetime.now().strftime('%Y%m%d')}{booking_id:04d}"
            
            cursor.execute("UPDATE bookings SET receipt_number = ? WHERE booking_id = ?",
                          (receipt_number, booking_id))
            
            conn.commit()
            conn.close()
            return booking_id
            
        except sqlite3.IntegrityError as e:
            if 'UNIQUE constraint failed: bookings.household_id, bookings.slot_id' in str(e):
                print("You already have a booking for this time slot.")
            else:
                print(f"Database error creating booking: {e}")
            return None
        except Exception as e:
            print(f"Error creating booking: {e}")
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
    
