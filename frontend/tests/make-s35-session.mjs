import { encode } from 'next-auth/jwt';

const secret = process.env.AUTH_SECRET ?? 's35-browser-secret';
const salt = 'authjs.session-token';
const token = {
  name: 'S3.5 Browser Admin',
  email: 'current-admin@s35.invalid',
  sub: '00000000-0000-4000-8000-000000000001',
  accessToken: 's35-browser-access-token',
  approval_status: 'approved',
  platform_role: 'admin',
  is_admin: false,
};

console.log(await encode({ token, secret, salt, maxAge: 60 * 60 }));
