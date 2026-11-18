/** Maximum database-issued lifetime for device and bound-session challenges.
 *
 * The signed Python Connector rejects challenges that expire more than 60 seconds
 * ahead of its own clock. Issue shorter challenges to tolerate modest host/DB
 * clock skew without relaxing the Connector's verification boundary.
 */
export const CONNECTOR_CHALLENGE_TTL_MS = 45_000;
