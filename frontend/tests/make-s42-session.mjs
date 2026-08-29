import { encode } from 'next-auth/jwt';

const secret = process.env.AUTH_SECRET ?? 's42-browser-secret';
const salt = 'authjs.session-token';
const token = {
  name: 'S4.2 Browser User',
  email: 'tenant-a@s42.invalid',
  sub: '42000000-0000-4000-8000-000000000001',
  accessToken: 's42-browser-access-token',
  approval_status: 'approved',
  platform_role: 'pilot_user',
  is_admin: false,
};

console.log(await encode({ token, secret, salt, maxAge: 60 * 60 }));
