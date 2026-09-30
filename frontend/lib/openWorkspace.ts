/**
 * One door (D1-06): open the pursuit workspace for a source tender.
 *
 * Pure orchestration so it can be tested without React. Nothing here runs on render:
 * the caller invokes `resolveWorkspace` from a click handler only.
 *
 *   1. resolve the organization context: exactly one ACTIVE membership is used
 *      automatically; several need an explicit choice; none is an error;
 *   2. create-or-resolve the SOURCE pursuit (POST /pursuits/source is idempotent per
 *      (organization, tender): 201 created, 200 existing);
 *   3. return the workspace URL.
 */

export type WorkspaceOrganization = {
    organization_id: string;
    display_name?: string | null;
    membership_state?: string | null;
};

export type WorkspaceDeps = {
    listOrganizations: () => Promise<WorkspaceOrganization[]>;
    createOrResolveSourcePursuit: (tenderId: string, organizationId: string) => Promise<{pursuit_id: string}>;
};

export type WorkspaceResolution =
    | {kind: 'navigate'; href: string; organizationId: string; pursuitId: string}
    | {kind: 'choose'; organizations: WorkspaceOrganization[]}
    | {kind: 'no-organization'};

export function activeOrganizations(organizations: WorkspaceOrganization[]): WorkspaceOrganization[] {
    return organizations.filter(
        (organization) => String(organization.membership_state ?? 'ACTIVE').toUpperCase() === 'ACTIVE',
    );
}

export function pursuitWorkspaceHref(pursuitId: string, organizationId: string): string {
    return `/dashboard/pursuits/${encodeURIComponent(pursuitId)}?organization_id=${encodeURIComponent(organizationId)}`;
}

/**
 * @param organizationId an explicit choice (from the picker); omit it on the first click.
 */
export async function resolveWorkspace(
    tenderId: string,
    deps: WorkspaceDeps,
    organizationId?: string,
): Promise<WorkspaceResolution> {
    let chosen = organizationId;
    if (!chosen) {
        const organizations = activeOrganizations(await deps.listOrganizations());
        if (organizations.length === 0) return {kind: 'no-organization'};
        if (organizations.length > 1) return {kind: 'choose', organizations};
        chosen = organizations[0].organization_id;
    }
    const pursuit = await deps.createOrResolveSourcePursuit(tenderId, chosen);
    return {
        kind: 'navigate',
        href: pursuitWorkspaceHref(pursuit.pursuit_id, chosen),
        organizationId: chosen,
        pursuitId: pursuit.pursuit_id,
    };
}
