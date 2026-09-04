import {encode} from 'next-auth/jwt';

const secret = process.env.AUTH_SECRET ?? 's72-browser-secret';
const salt = 'authjs.session-token';
const label = process.env.S72_USER_LABEL ?? 'a';
const accessToken = process.env.S72_ACCESS_TOKEN ?? `s72-token-${label}`;
const token = {
  name: `S7.2 Browser User ${label.toUpperCase()}`,
  email: `user-${label}@s72.invalid`,
  sub: `72000000-0000-4000-8000-00000000000${label === 'b' ? '2' : '1'}`,
  accessToken,
  approval_status: 'approved',
  platform_role: 'pilot_user',
  is_admin: false,
};

console.log(await encode({token, secret, salt, maxAge: 60 * 60}));
