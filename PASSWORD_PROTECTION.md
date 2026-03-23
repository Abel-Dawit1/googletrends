# Password Protection Setup

Your AbbVie Immunology Dashboard now includes password protection with an access code.

## How It Works

When users access the app, they will see a login screen asking for an **access code** before they can view the dashboard.

### Login Screen Features
- 🔒 Simple and clean login interface
- Password input field (text masked for security)
- "Login" button to submit the access code
- Error messages for incorrect codes
- Success confirmation on successful login

### Logout
Users can log out at any time by clicking the **🔐 Logout** button in the sidebar (bottom of the sidebar).

---

## Default Access Code

**Current Access Code: `1234`**

This is the default access code. Anyone accessing the app must enter this code to proceed.

---

## How to Change the Access Code

### Option 1: Edit `config.toml` (Recommended)

1. Open `config.toml` in your editor
2. Find the line: `ACCESS_CODE = "1234"`
3. Replace `"1234"` with your desired access code
4. Save the file

Example:
```toml
[secrets]
ACCESS_CODE = "mySecureCode123"
```

### Option 2: Set Environment Variable

If you're deploying to Streamlit Cloud or another platform, set an environment variable:

```bash
export STREAMLIT_SECRETS__ACCESS_CODE="mySecureCode123"
```

Or in your platform's settings, add a secret:
- Key: `ACCESS_CODE`
- Value: `mySecureCode123`

---

## Technical Details

### Code Implementation

The password protection is implemented in two places:

1. **Authentication Function** (`app.py` lines 50-82)
   - `check_authentication()` - Handles the login logic
   - Checks if user has authenticated via session state
   - Displays login form if not authenticated
   - Validates entered code against config value

2. **Configuration** (`config.toml`)
   - `ACCESS_CODE` setting under `[secrets]` section
   - Retrieved via `st.secrets.get("ACCESS_CODE")`

3. **Logout Button** (added to sidebar)
   - Clears authentication session state
   - Sends user back to login screen

### Session State

The app uses Streamlit's `session_state` to track authentication:
- `st.session_state.authenticated` - Boolean flag
- Persists only during user's session
- Resets when user logs out or closes browser

---

## Security Considerations

### ✅ Good Practices
- Change the default access code before deploying
- Use a numeric or alphanumeric code (characters, numbers, special symbols work)
- For production, consider a stronger code (8+ characters)
- Use environment variables for deployed instances

### ⚠️ Important Limitations
- This implementation provides **basic access control**
- Authentication is per-session (not persistent across browser restarts)
- Code is transmitted as plain text in page parameters
- For highly sensitive deployments, consider additional security measures:
  - HTTPS/TLS encryption
  - Multi-factor authentication
  - User database with password hashing
  - OAuth integration

---

## Testing the Login

To test the password protection:

1. Run the app: `streamlit run app.py`
2. Open browser to `http://localhost:8501`
3. You should see the login screen
4. Enter the access code (`1234` by default)
5. Click "Login"
6. If correct, you'll see "✓ Access granted!" and the dashboard loads
7. If incorrect, you'll see "❌ Incorrect access code. Please try again."
8. Click "🔐 Logout" button in sidebar to log out

---

## Troubleshooting

### Issue: Access code not working
**Solution:** 
- Verify the code in `config.toml` matches what you're entering
- Check for extra spaces or quotes in the config file
- Restart the Streamlit app after config changes

### Issue: Can't find the Logout button
**Solution:**
- Look at the bottom of the left sidebar
- It appears after the debug section

### Issue: Login page shows but keeps redirecting
**Solution:**
- Clear browser cache and cookies
- Try incognito/private browsing mode
- Check browser console for JavaScript errors

---

## Code Reference

### Authentication Function
```python
def check_authentication():
    """Check if user has provided correct access code."""
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    
    if not st.session_state.authenticated:
        # Display login form
        st.set_page_config(page_title="AbbVie Dashboard - Login", layout="centered")
        st.title("🔒 Access Required")
        
        access_code = st.text_input(
            "Access Code",
            type="password",
            placeholder="Enter access code",
            key="access_code_input"
        )
        
        if st.button("Login", use_container_width=True):
            correct_code = st.secrets.get("ACCESS_CODE", "1234")
            
            if access_code == correct_code:
                st.session_state.authenticated = True
                st.success("✓ Access granted!")
                st.rerun()
            else:
                st.error("❌ Incorrect access code. Please try again.")
        
        st.stop()
```

### Logout Button (in sidebar)
```python
if st.button("🔐 Logout", use_container_width=True):
    st.session_state.authenticated = False
    st.success("Logged out successfully")
    st.rerun()
```

---

## Future Enhancements

Consider these improvements for future versions:
- [ ] Multiple user accounts with different codes
- [ ] Rate limiting to prevent brute force attempts
- [ ] Login attempt logging
- [ ] Session timeout (auto-logout after inactivity)
- [ ] LDAP/Active Directory integration
- [ ] OAuth2 authentication
- [ ] Two-factor authentication (2FA)

---

For questions or issues, contact the development team.
