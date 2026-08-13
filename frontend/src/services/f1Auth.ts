/**
 * F1 TV Pro Authentication Service
 * 
 * Simple email/password authentication using F1's /authenticate/by-password endpoint.
 */

export interface F1AuthTokens {
    access_token: string;
    refresh_token?: string;
    expires_in?: number;
    token_type?: string;
    cookies?: string;
}

/**
 * Authenticate with F1 TV Pro using email and password.
 * 
 * @param email - F1 TV Pro account email
 * @param password - F1 TV Pro account password
 * @returns Authentication tokens and cookies
 */
export async function authenticateF1TV(email: string, password: string): Promise<F1AuthTokens> {
    try {
        // Use backend authentication endpoint
        const { authenticateF1TV: backendAuth } = await import('./api');
        const result = await backendAuth(email, password);
        
        const tokens: F1AuthTokens = {
            access_token: result.access_token,
            refresh_token: undefined,
            expires_in: undefined,
            token_type: 'Bearer',
            cookies: result.cookies,
        };

        // Store tokens in session storage for later use
        sessionStorage.setItem('f1_access_token', tokens.access_token);
        if (tokens.refresh_token) {
            sessionStorage.setItem('f1_refresh_token', tokens.refresh_token);
        }
        if (tokens.cookies) {
            sessionStorage.setItem('f1_cookies', tokens.cookies);
        }

        return tokens;
    } catch (error) {
        console.error('F1 TV Pro authentication error:', error);
        throw error;
    }
}

/**
 * Get stored authentication token from session storage.
 * 
 * @returns Access token if available, null otherwise
 */
export function getStoredAccessToken(): string | null {
    return sessionStorage.getItem('f1_access_token');
}

/**
 * Get stored refresh token from session storage.
 * 
 * @returns Refresh token if available, null otherwise
 */
export function getStoredRefreshToken(): string | null {
    return sessionStorage.getItem('f1_refresh_token');
}

/**
 * Get stored cookies from session storage.
 * 
 * @returns Cookies if available, null otherwise
 */
export function getStoredCookies(): string | null {
    return sessionStorage.getItem('f1_cookies');
}

/**
 * Clear stored authentication tokens and cookies.
 */
export function clearStoredTokens(): void {
    sessionStorage.removeItem('f1_access_token');
    sessionStorage.removeItem('f1_refresh_token');
    sessionStorage.removeItem('f1_cookies');
}

/**
 * Prompt user for F1 TV Pro credentials and authenticate.
 * This opens a dialog to collect email and password.
 * 
 * @returns Authentication tokens
 */
export async function promptAndAuthenticate(): Promise<F1AuthTokens> {
    return new Promise((resolve, reject) => {
        const email = prompt('Enter your F1 TV Pro email:');
        if (!email) {
            reject(new Error('Email is required'));
            return;
        }

        const password = prompt('Enter your F1 TV Pro password:');
        if (!password) {
            reject(new Error('Password is required'));
            return;
        }

        authenticateF1TV(email, password)
            .then(resolve)
            .catch(reject);
    });
}

/**
 * Authenticate using stored tokens or prompt for new credentials.
 * 
 * @returns Authentication tokens
 */
export async function authenticateWithPrompt(): Promise<F1AuthTokens> {
    // First, try to use stored token
    const storedToken = getStoredAccessToken();
    if (storedToken) {
        return {
            access_token: storedToken,
            refresh_token: getStoredRefreshToken() || undefined,
            cookies: getStoredCookies() || undefined,
        };
    }

    // If no stored token, prompt for credentials
    return promptAndAuthenticate();
}
