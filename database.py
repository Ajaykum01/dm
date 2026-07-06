import logging
import psycopg2
from psycopg2 import pool
from datetime import datetime
from typing import Optional, Tuple, List
import os
from dotenv import load_dotenv
import json
import random
import string

# ==============================
# Load environment variables
# ==============================
load_dotenv()

# ==============================
# Logging Setup
# ==============================
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ==============================
# Database Configuration
# ==============================
DB_HOST = "ep-fragrant-cell-anmpsax8-pooler.c-6.us-east-1.aws.neon.tech"
DB_USER = "neondb_owner"
DB_PASSWORD = "npg_yMQ0ulYSL9hb"
DB_PASS = DB_PASSWORD  
DB_NAME = "neondb"
DB_PORT = 5432
# ==============================
# Constants
# ==============================
DEFAULT_CREDITS = 250

# ==============================
# Global Connection Pool
# ==============================
connection_pool: pool.SimpleConnectionPool | None = None

# ==============================
# Create Connection Pool
# ==============================
def create_connection_pool(sslmode="require") -> bool:
    """Initialize PostgreSQL connection pool."""
    global connection_pool
    try:
        connection_pool = psycopg2.pool.SimpleConnectionPool(
            minconn=1,
            maxconn=20,  # Handle more simultaneous users
            user=DB_USER,
            password=DB_PASS,
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME
        )
        if connection_pool:
            logger.info("✅ Database connection pool created successfully.")
            return True
    except Exception as e:
        logger.error(f"❌ Error creating connection pool: {e}")
    return False

# ==============================
# Close Connection Pool
# ==============================
def close_connection_pool() -> None:
    """Close all connections in the pool."""
    global connection_pool
    if connection_pool:
        connection_pool.closeall()
        logger.info("🔒 Database connection pool closed.")

# ==============================
# Setup Database Tables
# ==============================
def setup_database() -> None:
    """Ensure users, user_plans, and redeem_codes tables exist."""
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return

    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            # Create users table (with proxies column as JSON)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    joined_at TIMESTAMP DEFAULT NOW(),
                    tier TEXT DEFAULT 'Trial',
                    credits INT DEFAULT 250,
                    proxies JSONB DEFAULT '[]'::jsonb
                )
            """)
            
            # Create user_plans table for managing paid plans
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_plans (
                    user_id BIGINT PRIMARY KEY,
                    tier TEXT NOT NULL,
                    expiry_date TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                )
            """)
            
            # Create redeem_codes table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS redeem_codes (
                    id SERIAL PRIMARY KEY,
                    code VARCHAR(20) UNIQUE NOT NULL,
                    tier VARCHAR(20) NOT NULL,
                    duration_days INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW(),
                    used_at TIMESTAMP NULL,
                    used_by BIGINT NULL
                )
            """)
            
            conn.commit()
            logger.info("✅ Database tables checked/created successfully.")
    except Exception as e:
        logger.error(f"❌ Error setting up database: {e}")
    finally:
        connection_pool.putconn(conn)

# ==============================
# Get or Create User
# ==============================
def get_or_create_user(user_id: int, username: str) -> tuple[str, datetime, str, int] | None:
    """
    Get user info or create a new entry if not exists.
    Returns: (username, joined_at, tier, credits)
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return None

    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            # Check if user exists
            cur.execute(
                "SELECT username, joined_at, tier, credits FROM users WHERE user_id = %s",
                (user_id,)
            )
            result = cur.fetchone()

            if result:
                db_username, joined_at, tier, credits = result

                # Update username if changed
                if db_username != username:
                    cur.execute(
                        "UPDATE users SET username = %s WHERE user_id = %s",
                        (username, user_id)
                    )
                    conn.commit()
                    logger.info(f"📝 Updated username for user {user_id} → {username}")

                # Ensure tier is not empty
                if not tier:
                    tier = "Trial"

                return (db_username, joined_at, tier, credits)

            # Insert new user with Trial tier and 250 credits
            joined_at = datetime.now()
            cur.execute("""
                INSERT INTO users (user_id, username, joined_at, tier, credits)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING username, joined_at, tier, credits
            """, (user_id, username, joined_at, "Trial", DEFAULT_CREDITS))
            conn.commit()

            result = cur.fetchone()
            logger.info(f"👤 New user added → {username} ({user_id}) with Trial tier and {DEFAULT_CREDITS} credits")
            return result
    except Exception as e:
        logger.error(f"❌ Database error in get_or_create_user: {e}")
        return None
    finally:
        connection_pool.putconn(conn)

# ==============================
# Update User Credits
# ==============================
def update_user_credits(user_id: int, credits_change: int) -> bool:
    """
    Update user credits by adding or subtracting the specified amount.
    
    Args:
        user_id: The Telegram user ID
        credits_change: The amount to change (positive to add, negative to subtract)
        
    Returns:
        True if successful, False otherwise
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return False

    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            # Update credits
            cur.execute(
                "UPDATE users SET credits = credits + %s WHERE user_id = %s",
                (credits_change, user_id)
            )
            conn.commit()
            
            # Check if any row was affected
            if cur.rowcount > 0:
                # Get updated credits
                cur.execute("SELECT credits FROM users WHERE user_id = %s", (user_id,))
                new_credits = cur.fetchone()[0]
                logger.info(f"💰 Updated credits for user {user_id}: {credits_change:+d} → {new_credits}")
                return True
            else:
                logger.warning(f"⚠️ User {user_id} not found when updating credits")
                return False
    except Exception as e:
        logger.error(f"❌ Database error in update_user_credits: {e}")
        return False
    finally:
        connection_pool.putconn(conn)

# ==============================
# Get User Credits
# ==============================
def get_user_credits(user_id: int) -> int | None:
    """
    Get the current credit balance for a user.
    Returns unlimited credits if the user has an active, non-expired plan.
    
    Args:
        user_id: The Telegram user ID
        
    Returns:
        The current credit balance, float('inf') for unlimited, or None if user not found
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return None

    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            # First, check if the user has an active plan
            cur.execute(
                "SELECT tier, expiry_date FROM user_plans WHERE user_id = %s",
                (user_id,)
            )
            plan_result = cur.fetchone()
            
            # If user has an active plan that hasn't expired, return unlimited credits
            if plan_result:
                tier, expiry_date = plan_result
                if expiry_date and datetime.now() <= expiry_date:
                    logger.info(f"✅ User {user_id} has active plan {tier}, unlimited credits")
                    return float('inf')  # Use infinity to represent unlimited
            
            # If no active plan, get the actual credit balance from the users table
            cur.execute("SELECT credits FROM users WHERE user_id = %s", (user_id,))
            result = cur.fetchone()
            return result[0] if result else None
    except Exception as e:
        logger.error(f"❌ Database error in get_user_credits: {e}")
        return None
    finally:
        connection_pool.putconn(conn)

# ==============================
# Update User Plan
# ==============================
def update_user_plan(user_id: int, tier: str, expiry_date: Optional[datetime]) -> bool:
    """
    Update a user's plan tier and expiry date in the user_plans table.
    Also updates the tier in the main users table.
    If tier is set to "Trial", credits are reset to the default value.
    
    Args:
        user_id: The user ID
        tier: The new tier (Core, Elite, Root, X, or Trial)
        expiry_date: The expiry date for the plan, or None for Trial
        
    Returns:
        True if successful, False otherwise
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return False
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            # First, check if the user exists in the users table
            cur.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
            user_exists = cur.fetchone()
            
            if not user_exists:
                logger.warning(f"⚠️ User {user_id} does not exist in users table, cannot update plan")
                return False
            
            # Check if user already has a plan record
            cur.execute("SELECT user_id FROM user_plans WHERE user_id = %s", (user_id,))
            exists = cur.fetchone()
            
            if exists:
                # Update existing record
                if expiry_date:
                    cur.execute(
                        "UPDATE user_plans SET tier = %s, expiry_date = %s WHERE user_id = %s",
                        (tier, expiry_date, user_id)
                    )
                else:
                    cur.execute(
                        "UPDATE user_plans SET tier = %s, expiry_date = NULL WHERE user_id = %s",
                        (tier, user_id)
                    )
            else:
                # Insert new record
                if expiry_date:
                    cur.execute(
                        "INSERT INTO user_plans (user_id, tier, expiry_date) VALUES (%s, %s, %s)",
                        (user_id, tier, expiry_date)
                    )
                else:
                    cur.execute(
                        "INSERT INTO user_plans (user_id, tier, expiry_date) VALUES (%s, %s, NULL)",
                        (user_id, tier)
                    )
            
            # If user is being reverted to Trial, reset their credits
            if tier == "Trial":
                cur.execute(
                    "UPDATE users SET tier = %s, credits = %s WHERE user_id = %s",
                    (tier, DEFAULT_CREDITS, user_id)
                )
                logger.info(f"🔄 User {user_id} reverted to Trial, credits reset to {DEFAULT_CREDITS}")
            else:
                # Otherwise, just update the tier
                cur.execute(
                    "UPDATE users SET tier = %s WHERE user_id = %s",
                    (tier, user_id)
                )
            
            conn.commit()
            logger.info(f"✅ Updated plan for user {user_id} to {tier}. Expires: {expiry_date}")
            return True
    except Exception as e:
        logger.error(f"❌ Database error in update_user_plan: {e}")
        conn.rollback()
        return False
    finally:
        connection_pool.putconn(conn)

# ==============================
# Get User Plan
# ==============================
def get_user_plan(user_id: int) -> Optional[Tuple[str, Optional[datetime]]]:
    """
    Get a user's plan tier and expiry date from the user_plans table.
    
    Args:
        user_id: The user ID
        
    Returns:
        A tuple of (tier, expiry_date) or None if not found
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return None
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tier, expiry_date FROM user_plans WHERE user_id = %s",
                (user_id,)
            )
            result = cur.fetchone()
            return result
    except Exception as e:
        logger.error(f"❌ Database error in get_user_plan: {e}")
        return None
    finally:
        connection_pool.putconn(conn)

# ==============================
# Get User Data
# ==============================
def get_user_data(user_id: int) -> Optional[dict]:
    """
    Get all user data.
    
    Args:
        user_id: The user ID
        
    Returns:
        A dictionary with user data or None if not found
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return None
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT username, joined_at, tier, credits, proxies FROM users WHERE user_id = %s",
                (user_id,)
            )
            result = cur.fetchone()
            
            if result:
                username, joined_at, tier, credits, proxies = result
                return {
                    "username": username,
                    "joined_at": joined_at,
                    "tier": tier,
                    "credits": credits,
                    "proxies": proxies if proxies else []
                }
            return None
    except Exception as e:
        logger.error(f"❌ Database error in get_user_data: {e}")
        return None
    finally:
        connection_pool.putconn(conn)

# ==============================
# Update User Data
# ==============================
def update_user_data(user_id: int, data: dict) -> bool:
    """
    Update specific user data fields.
    
    Args:
        user_id: The user ID
        data: Dictionary with fields to update
        
    Returns:
        True if successful, False otherwise
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return False
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            # Build the update query dynamically based on provided data
            update_fields = []
            update_values = []
            
            for field, value in data.items():
                update_fields.append(f"{field} = %s")
                update_values.append(value)
            
            if not update_fields:
                return False  # Nothing to update
            
            # Add user_id to the values
            update_values.append(user_id)
            
            # Execute the update query
            cur.execute(
                f"UPDATE users SET {', '.join(update_fields)} WHERE user_id = %s",
                update_values
            )
            conn.commit()
            
            if cur.rowcount > 0:
                logger.info(f"✅ Updated user data for user {user_id}")
                return True
            else:
                logger.warning(f"⚠️ User {user_id} not found when updating data")
                return False
    except Exception as e:
        logger.error(f"❌ Database error in update_user_data: {e}")
        conn.rollback()
        return False
    finally:
        connection_pool.putconn(conn)

# ==============================
# Save Redeem Code
# ==============================
def save_redeem_code(code: str, tier: str, duration_days: int) -> bool:
    """
    Save a new redeem code to the database.
    
    Args:
        code: The redeem code
        tier: The plan tier
        duration_days: Duration in days
        
    Returns:
        True if successful, False otherwise
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return False
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            # Insert the new code
            cur.execute(
                "INSERT INTO redeem_codes (code, tier, duration_days) VALUES (%s, %s, %s)",
                (code, tier, duration_days)
            )
            conn.commit()
            
            logger.info(f"✅ Created redeem code {code} for {tier} plan")
            return True
    except Exception as e:
        logger.error(f"❌ Database error in save_redeem_code: {e}")
        conn.rollback()
        return False
    finally:
        connection_pool.putconn(conn)

# ==============================
# Get Redeem Code Info
# ==============================
def get_redeem_code_info(code: str) -> Optional[dict]:
    """
    Get information about a redeem code.
    
    Args:
        code: The redeem code
        
    Returns:
        Dictionary with code info or None if not found/used
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return None
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            # Get the code info
            cur.execute(
                "SELECT tier, duration_days, used_at FROM redeem_codes WHERE code = %s",
                (code,)
            )
            result = cur.fetchone()
            
            if not result:
                return None
            
            tier, duration_days, used_at = result
            
            # Check if the code has already been used
            if used_at:
                return None
            
            return {
                "tier": tier,
                "duration_days": duration_days
            }
    except Exception as e:
        logger.error(f"❌ Database error in get_redeem_code_info: {e}")
        return None
    finally:
        connection_pool.putconn(conn)

# ==============================
# Mark Redeem Code as Used
# ==============================
def mark_redeem_code_as_used(code: str, user_id: int) -> bool:
    """
    Mark a redeem code as used.
    
    Args:
        code: The redeem code
        user_id: The user who used it
        
    Returns:
        True if successful, False otherwise
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return False
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            # Update the code as used
            cur.execute(
                "UPDATE redeem_codes SET used_at = NOW(), used_by = %s WHERE code = %s",
                (user_id, code)
            )
            conn.commit()
            
            if cur.rowcount > 0:
                logger.info(f"✅ Marked redeem code {code} as used by user {user_id}")
                return True
            else:
                logger.warning(f"⚠️ Redeem code {code} not found when marking as used")
                return False
    except Exception as e:
        logger.error(f"❌ Database error in mark_redeem_code_as_used: {e}")
        conn.rollback()
        return False
    finally:
        connection_pool.putconn(conn)

# ==============================
# Get All Redeem Codes
# ==============================
def get_all_redeem_codes() -> List[dict]:
    """
    Get all redeem codes from the database.
    
    Returns:
        List of dictionaries with code info
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return []
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT code, tier, duration_days, created_at, used_at, used_by FROM redeem_codes ORDER BY created_at DESC"
            )
            results = cur.fetchall()
            
            codes = []
            for result in results:
                code, tier, duration_days, created_at, used_at, used_by = result
                codes.append({
                    "code": code,
                    "tier": tier,
                    "duration_days": duration_days,
                    "created_at": created_at,
                    "used_at": used_at,
                    "used_by": used_by
                })
            
            return codes
    except Exception as e:
        logger.error(f"❌ Database error in get_all_redeem_codes: {e}")
        return []
    finally:
        connection_pool.putconn(conn)

# ==============================
# Check if User Has Active Plan
# ==============================
def has_user_active_plan(user_id: int) -> bool:
    """
    Check if a user currently has an active plan.
    
    Args:
        user_id: The user ID to check
        
    Returns:
        True if user has an active plan, False otherwise
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return False
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            # Check if user has an active plan
            cur.execute(
                "SELECT tier, expiry_date FROM user_plans WHERE user_id = %s",
                (user_id,)
            )
            result = cur.fetchone()
            
            if result:
                tier, expiry_date = result
                # Check if the plan has expired
                if expiry_date and datetime.now() <= expiry_date:
                    return True
                else:
                    return False
            return False
    except Exception as e:
        logger.error(f"❌ Database error in has_user_active_plan: {e}")
        return False
    finally:
        connection_pool.putconn(conn)

# ==============================
# Check if User Has Redeemed Before
# ==============================
def has_user_redeemed_before(user_id: int) -> bool:
    """
    Check if a user has already redeemed a code before.
    
    Args:
        user_id: The user ID to check
        
    Returns:
        True if user has redeemed before, False otherwise
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return False
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            # Check if user has any used codes
            cur.execute(
                "SELECT COUNT(*) FROM redeem_codes WHERE used_by = %s",
                (user_id,)
            )
            count = cur.fetchone()[0]
            
            return count > 0
    except Exception as e:
        logger.error(f"❌ Database error in has_user_redeemed_before: {e}")
        return False
    finally:
        connection_pool.putconn(conn)

# ==============================
# Add User Proxy
# ==============================
def add_user_proxy(user_id: int, proxy: str) -> Tuple[bool, str]:
    """
    Add a proxy to the user's proxy list.
    
    Args:
        user_id: The user ID
        proxy: The proxy string to add
        
    Returns:
        Tuple of (success, message)
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return False, "Database connection error"
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            # Get current proxies
            cur.execute("SELECT proxies FROM users WHERE user_id = %s", (user_id,))
            result = cur.fetchone()
            
            if not result:
                return False, "User not found"
            
            current_proxies = result[0] if result[0] else []
            
            # Check if proxy already exists
            if proxy in current_proxies:
                return False, "Proxy already exists"
            
            # Check if user has reached the limit
            if len(current_proxies) >= 10:
                return False, "Proxy limit reached (10)"
            
            # Add the new proxy
            current_proxies.append(proxy)
            
            # Update the database
            cur.execute(
                "UPDATE users SET proxies = %s WHERE user_id = %s",
                (json.dumps(current_proxies), user_id)
            )
            conn.commit()
            
            logger.info(f"✅ Added proxy for user {user_id}")
            return True, "Proxy added successfully"
    except Exception as e:
        logger.error(f"❌ Database error in add_user_proxy: {e}")
        return False, f"Database error: {str(e)}"
    finally:
        connection_pool.putconn(conn)

# ==============================
# Remove User Proxies
# ==============================
def remove_user_proxies(user_id: int, count: int) -> Tuple[bool, str]:
    """
    Remove a specified number of proxies from the user's proxy list.
    If count is -1, remove all proxies.
    
    Args:
        user_id: The user ID
        count: The number of proxies to remove, or -1 to remove all
        
    Returns:
        Tuple of (success, message)
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return False, "Database connection error"
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            # Get current proxies
            cur.execute("SELECT proxies FROM users WHERE user_id = %s", (user_id,))
            result = cur.fetchone()
            
            if not result:
                return False, "User not found"
            
            current_proxies = result[0] if result[0] else []
            
            if not current_proxies:
                return False, "No proxies to remove"
            
            # If count is -1, remove all proxies
            if count == -1:
                removed_count = len(current_proxies)
                remaining_proxies = []
            else:
                # Remove the specified number of proxies
                removed_count = min(count, len(current_proxies))
                remaining_proxies = current_proxies[removed_count:]
            
            # Update the database
            cur.execute(
                "UPDATE users SET proxies = %s WHERE user_id = %s",
                (json.dumps(remaining_proxies), user_id)
            )
            conn.commit()
            
            logger.info(f"✅ Removed {removed_count} proxies for user {user_id}")
            return True, f"Removed {removed_count} proxies"
    except Exception as e:
        logger.error(f"❌ Database error in remove_user_proxies: {e}")
        return False, f"Database error: {str(e)}"
    finally:
        connection_pool.putconn(conn)

# ==============================
# Get User Proxies
# ==============================
def get_user_proxies(user_id: int) -> List[str]:
    """
    Get all proxies for a user.
    
    Args:
        user_id: The user ID
        
    Returns:
        List of proxy strings
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return []
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT proxies FROM users WHERE user_id = %s", (user_id,))
            result = cur.fetchone()
            
            if result and result[0]:
                return result[0]
            return []
    except Exception as e:
        logger.error(f"❌ Database error in get_user_proxies: {e}")
        return []
    finally:
        connection_pool.putconn(conn)

# ==============================
# Get Random User Proxy
# ==============================
def get_random_user_proxy(user_id: int) -> Optional[str]:
    """
    Get a random proxy from the user's proxy list.
    
    Args:
        user_id: The user ID
        
    Returns:
        A random proxy string or None if no proxies
    """
    proxies = get_user_proxies(user_id)
    if proxies:
        return random.choice(proxies)
    return None

# ==============================
# Get User Gate Status
# ==============================
def get_user_gate_status(user_id: int) -> Optional[dict]:
    """
    Get a user's gate status from the database.
    
    Args:
        user_id: The user ID
        
    Returns:
        Dictionary with gate status or None if not found
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return None
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            # Create a gate_status table if it doesn't exist
            cur.execute("""
                CREATE TABLE IF NOT EXISTS gate_status (
                    user_id BIGINT PRIMARY KEY,
                    gate_status JSONB DEFAULT '{}'::jsonb,
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            # Get the user's gate status
            cur.execute(
                "SELECT gate_status FROM gate_status WHERE user_id = %s",
                (user_id,)
            )
            result = cur.fetchone()
            
            if result and result[0]:
                return result[0]
            
            # Return default gate status if not found
            return {
                "rz": {"enabled": True, "message": "Razorpay 1₹ gate is currently active"},
                "sh": {"enabled": True, "message": "Shopify 0.98$ gate is currently active"},
                "chk": {"enabled": True, "message": "Stripe Auth gate is currently active"},
                "mass": {"enabled": True, "message": "Mass Stripe Auth gate is currently active"},
                "at": {"enabled": True, "message": "Authnet 1$ gate is currently active"},
                "gate": {"enabled": True, "message": "Gateway status checker is currently active"},
                "msh": {"enabled": True, "message": "Shopify Random gate is currently active"},
                "vbv": {"enabled": True, "message": "3DS Lookup gate is currently active"},
                "st": {"enabled": True, "message": "Stripe 1$ gate is currently active"},
                "stt": {"enabled": True, "message": "Stripe 5$ gate is currently active"},
                "st1": {"enabled": True, "message": "Stripe 1€ gate is currently active"},
                "pp": {"enabled": True, "message": "Paypal 1$ gate is currently active"},
                "p1": {"enabled": True, "message": "Paypal 0.10$ gate is currently active"},
                "py": {"enabled": True, "message": "PayU 1$ gate is currently active"},
                "pu": {"enabled": True, "message": "PayU 0.1€ gate is currently active"},
                "pyu": {"enabled": True, "message": "PayU 1 PLN gate is currently active"},
                "sk": {"enabled": True, "message": "SK Based 1$ gate is currently active"},
                "mpp": {"enabled": True, "message": "Paypal 1$ gate is currently active"},
                "msk": {"enabled": True, "message": "SK Based Mass 1$ gate is currently active"},
                "pv": {"enabled": True, "message": "Paypal 1$ CVV gate is currently active"},
                "gen": {"enabled": True, "message": "Card Generator is currently active"},
                "proxy": {"enabled": True, "message": "Proxy Manager is currently active"},
                "rproxy": {"enabled": True, "message": "Random Proxy is currently active"},
                "myproxy": {"enabled": True, "message": "My Proxy is currently active"}
            }
    except Exception as e:
        logger.error(f"❌ Database error in get_user_gate_status: {e}")
        return None
    finally:
        connection_pool.putconn(conn)

# ==============================
# Update User Gate Status
# ==============================
def update_user_gate_status(user_id: int, gate_status: dict) -> bool:
    """
    Update a user's gate status in the database.
    
    Args:
        user_id: The user ID
        gate_status: Dictionary with gate status
        
    Returns:
        True if successful, False otherwise
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return False
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            # Create a gate_status table if it doesn't exist
            cur.execute("""
                CREATE TABLE IF NOT EXISTS gate_status (
                    user_id BIGINT PRIMARY KEY,
                    gate_status JSONB DEFAULT '{}'::jsonb,
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            # Check if user already has a gate status record
            cur.execute("SELECT user_id FROM gate_status WHERE user_id = %s", (user_id,))
            exists = cur.fetchone()
            
            if exists:
                # Update existing record
                cur.execute(
                    "UPDATE gate_status SET gate_status = %s, updated_at = NOW() WHERE user_id = %s",
                    (json.dumps(gate_status), user_id)
                )
            else:
                # Insert new record
                cur.execute(
                    "INSERT INTO gate_status (user_id, gate_status) VALUES (%s, %s)",
                    (user_id, json.dumps(gate_status))
                )
            
            conn.commit()
            logger.info(f"✅ Updated gate status for user {user_id}")
            return True
    except Exception as e:
        logger.error(f"❌ Database error in update_user_gate_status: {e}")
        conn.rollback()
        return False
    finally:
        connection_pool.putconn(conn)

# ==============================
# Get Total Users
# ==============================
def get_total_users() -> int:
    """
    Get the total number of users in the database.
    
    Returns:
        Total number of users
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return 0
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users")
            count = cur.fetchone()
            return count[0] if count else 0
    except Exception as e:
        logger.error(f"❌ Database error in get_total_users: {e}")
        return 0
    finally:
        connection_pool.putconn(conn)

# ==============================
# Generate Plan Code
# ==============================
def generate_plan_code(tier: str, duration_days: int) -> Optional[str]:
    """
    Generate a new plan code for the specified tier and duration.
    
    Args:
        tier: The plan tier (Core, Elite, Root, X)
        duration_days: Duration in days
        
    Returns:
        The generated code or None if failed
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return None
    
    # Generate a random code
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))
    
    # Save the code to the database
    if save_redeem_code(code, tier, duration_days):
        return code
    return None

# ==============================
# Generate Multiple Plan Codes
# ==============================
def generate_multiple_plan_codes(tier: str, duration_days: int, count: int) -> List[str]:
    """
    Generate multiple plan codes for the specified tier and duration.
    
    Args:
        tier: The plan tier (Core, Elite, Root, X)
        duration_days: Duration in days
        count: Number of codes to generate
        
    Returns:
        List of generated codes
    """
    codes = []
    for _ in range(count):
        code = generate_plan_code(tier, duration_days)
        if code:
            codes.append(code)
    
    return codes

# ==============================
# Get All Active Plans
# ==============================
def get_all_active_plans() -> list[tuple[int, str, datetime]]:
    """
    Get all users who currently have an active (non-expired) plan.
    
    Returns:
        List of tuples: (user_id, tier, expiry_date)
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return []

    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT user_id, tier, expiry_date
                FROM user_plans
                WHERE expiry_date IS NOT NULL
                ORDER BY expiry_date ASC
            """)
            results = cur.fetchall()
            return results if results else []
    except Exception as e:
        logger.error(f"❌ Database error in get_all_active_plans: {e}")
        return []
    finally:
        connection_pool.putconn(conn)

def get_all_user_ids() -> list[int]:
    """
    Get all Telegram user IDs from users table.
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return []

    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM users")
            rows = cur.fetchall()
            return [row[0] for row in rows]
    except Exception as e:
        logger.error(f"❌ Database error in get_all_user_ids: {e}")
        return []
    finally:
        connection_pool.putconn(conn)

# ==============================
# Custom Gates Table Setup
# ==============================

def setup_custom_gates_table() -> None:
    """Ensure the custom_gates table exists."""
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return

    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS custom_gates (
                    id SERIAL PRIMARY KEY,
                    gate_name VARCHAR(50) UNIQUE NOT NULL,
                    site_url TEXT NOT NULL,
                    created_by BIGINT,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            conn.commit()
            logger.info("✅ Custom gates table checked/created.")
    except Exception as e:
        logger.error(f"❌ Error creating custom_gates table: {e}")
    finally:
        connection_pool.putconn(conn)

# ==============================
# Add Custom Gate
# ==============================
def add_custom_gate(gate_name: str, site_url: str, user_id: int) -> bool:
    """
    Save a new custom gate to the database.
    
    Args:
        gate_name: The command name (e.g., 'sp')
        site_url: The Shopify site URL
        user_id: The Telegram ID of the user creating it
        
    Returns:
        True if successful, False otherwise (e.g., duplicate name)
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return False
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO custom_gates (gate_name, site_url, created_by) VALUES (%s, %s, %s)",
                (gate_name, site_url, user_id)
            )
            conn.commit()
            logger.info(f"✅ Custom gate '{gate_name}' added by user {user_id} -> {site_url}")
            return True
    except psycopg2.errors.UniqueViolation:
        logger.warning(f"⚠️ Gate name '{gate_name}' already exists.")
        return False
    except Exception as e:
        logger.error(f"❌ Database error in add_custom_gate: {e}")
        return False
    finally:
        connection_pool.putconn(conn)

# ==============================
# Get Custom Gate URL
# ==============================
def get_custom_gate_url(gate_name: str) -> Optional[str]:
    """
    Retrieve the site URL for a given custom gate command.
    
    Args:
        gate_name: The command name (e.g., 'sp')
        
    Returns:
        The site URL string or None if not found
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return None
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT site_url FROM custom_gates WHERE gate_name = %s",
                (gate_name,)
            )
            result = cur.fetchone()
            return result[0] if result else None
    except Exception as e:
        logger.error(f"❌ Database error in get_custom_gate_url: {e}")
        return None
    finally:
        connection_pool.putconn(conn)

# ==============================
# Is Custom Gate
# ==============================
def is_custom_gate(gate_name: str) -> bool:
    """Check if a command name is a registered custom gate."""
    return get_custom_gate_url(gate_name) is not None

# ==============================
# Delete Custom Gate
# ==============================
def delete_custom_gate(gate_name: str) -> bool:
    """
    Delete a custom gate from the database by name.
    
    Args:
        gate_name: The command name (e.g., 'sp')
        
    Returns:
        True if a row was deleted, False if not found
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return False
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM custom_gates WHERE gate_name = %s",
                (gate_name,)
            )
            conn.commit()
            
            if cur.rowcount > 0:
                logger.info(f"✅ Deleted custom gate '{gate_name}'")
                return True
            else:
                return False
    except Exception as e:
        logger.error(f"❌ Database error in delete_custom_gate: {e}")
        return False
    finally:
        connection_pool.putconn(conn)

# ==============================
# Get All Gates
# ==============================
def get_all_gates() -> List[tuple]:
    """
    Get all custom gates from database.
    Required for /lisgates command.
    
    Returns:
        List of tuples: [(gate_name, site_url), ...]
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return []
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            # We select BOTH gate_name AND site_url because the main script expects index 0 and 1
            cur.execute("SELECT gate_name, site_url FROM custom_gates")
            results = cur.fetchall()
            return results if results else []
    except Exception as e:
        logger.error(f"❌ Database error in get_all_gates: {e}")
        return []
    finally:
        connection_pool.putconn(conn)
# ==============================
# Update Custom Gate
# ==============================
def update_custom_gate(gate_name: str, site_url: str) -> bool:
    """
    Update the sites for an existing custom gate.
    
    Args:
        gate_name: The command name (e.g., 'sp')
        site_url: The new list of sites (comma-separated string)
        
    Returns:
        True if successful, False otherwise
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return False

    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE custom_gates SET site_url = %s WHERE gate_name = %s",
                (site_url, gate_name)
            )
            conn.commit()
            
            if cur.rowcount > 0:
                logger.info(f"✅ Updated custom gate '{gate_name}'")
                return True
            else:
                logger.warning(f"⚠️ Gate '{gate_name}' not found for update.")
                return False
    except Exception as e:
        logger.error(f"❌ Database error in update_custom_gate: {e}")
        return False
    finally:
        connection_pool.putconn(conn)
