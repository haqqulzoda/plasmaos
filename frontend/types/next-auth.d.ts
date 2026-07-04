import { DefaultSession } from 'next-auth';

declare module 'next-auth' {
  interface Session {
    accessToken?: string;
    platform_role?: string;
    approval_status?: string;
    is_admin?: boolean;
    onboarding_required?: boolean;
    company_profile_id?: string | null;
    company_approval_status?: string | null;
    company_pilot_status?: string | null;
    user: DefaultSession['user'] & {
      platform_role?: string;
      approval_status?: string;
      is_admin?: boolean;
      onboarding_required?: boolean;
      company_profile_id?: string | null;
      company_approval_status?: string | null;
      company_pilot_status?: string | null;
    };
  }

  interface User {
    accessToken?: string;
  }
}

declare module 'next-auth/jwt' {
  interface JWT {
    accessToken?: string;
    platform_role?: string;
    approval_status?: string;
    is_admin?: boolean;
    onboarding_required?: boolean;
    company_profile_id?: string | null;
    company_approval_status?: string | null;
    company_pilot_status?: string | null;
  }
}
