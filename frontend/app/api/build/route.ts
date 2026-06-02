import { NextResponse } from 'next/server';

export async function GET() {
    return NextResponse.json({
        status: 'ok',
        build_sha: process.env.PLASMA_BUILD_SHA ?? process.env.NEXT_PUBLIC_BUILD_SHA ?? 'unknown',
        build_time: process.env.PLASMA_BUILD_TIME ?? 'unknown',
        node_env: process.env.NODE_ENV ?? 'unknown',
    });
}
