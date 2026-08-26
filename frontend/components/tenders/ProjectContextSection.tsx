import {
    AlertCircle,
    ExternalLink,
    Globe2,
    History,
    Loader2,
    UsersRound,
} from 'lucide-react';

import {
    formatProjectDate,
    projectFreshnessMessage,
    projectMetadataRows,
    projectRoleLabel,
    projectSourceLabel,
    type ProjectContextRole,
    type TenderProjectContext,
} from '@/types/project';

interface ProjectContextSectionProps {
    context: TenderProjectContext | null;
    isLoading: boolean;
    failed: boolean;
    fallbackIdentity: {
        sourceSystem: string;
        externalProjectId: string;
    } | null;
}

function RoleRow({ role, historical = false }: { role: ProjectContextRole; historical?: boolean }) {
    return (
        <div className="min-w-0 rounded-md border border-zinc-800 bg-zinc-900/50 px-3 py-3">
            <div className="flex min-w-0 flex-col gap-1 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
                <div className="min-w-0">
                    <p className="font-medium text-zinc-100">{role.display_name}</p>
                    <p className="mt-1 text-xs text-zinc-400">{projectRoleLabel(role)}</p>
                </div>
                <p className="shrink-0 text-xs text-zinc-500">
                    {historical && role.ended_at
                        ? `Observed until ${formatProjectDate(role.ended_at)} · ${projectSourceLabel(role.source_system)}`
                        : projectSourceLabel(role.source_system)}
                </p>
            </div>
            {(role.email || role.phone) ? (
                <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-400">
                    {role.email ? <span>{role.email}</span> : null}
                    {role.phone ? <span>{role.phone}</span> : null}
                </div>
            ) : null}
        </div>
    );
}

export function ProjectContextSection({
    context,
    isLoading,
    failed,
    fallbackIdentity,
}: ProjectContextSectionProps) {
    if (!context && !fallbackIdentity) return null;

    if (!context) {
        return (
            <section aria-labelledby="project-context-heading" className="rounded-lg border border-sky-500/20 bg-gray-950 p-5">
                <div className="flex items-start gap-3">
                    {isLoading ? (
                        <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-sky-300" aria-hidden="true" />
                    ) : (
                        <Globe2 className="mt-0.5 h-4 w-4 shrink-0 text-sky-300" aria-hidden="true" />
                    )}
                    <div>
                        <h2 id="project-context-heading" className="text-lg font-semibold text-white">Project Context</h2>
                        <p className="mt-2 text-sm font-medium text-zinc-200">
                            {projectSourceLabel(fallbackIdentity?.sourceSystem)} Project · {fallbackIdentity?.externalProjectId}
                        </p>
                        <p role="status" className="mt-1 text-sm text-zinc-500">
                            {failed ? 'Project details are temporarily unavailable.' : 'Project details are being prepared.'}
                        </p>
                    </div>
                </div>
            </section>
        );
    }

    const { project, current_roles: currentRoles, historical_roles: historicalRoles } = context;
    const metadataRows = projectMetadataRows(project);
    const freshnessMessage = projectFreshnessMessage(project.source_freshness);
    const sourceName = projectSourceLabel(project.source_system);

    return (
        <section aria-labelledby="project-context-heading" className="rounded-lg border border-sky-500/20 bg-gray-950 p-5 shadow-[0_0_0_1px_rgba(14,165,233,0.04)]">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                    <div className="flex items-center gap-2">
                        <Globe2 className="h-4 w-4 shrink-0 text-sky-300" aria-hidden="true" />
                        <h2 id="project-context-heading" className="text-lg font-semibold text-white">Project Context</h2>
                    </div>
                    {project.name ? <h3 className="mt-3 text-base font-semibold text-zinc-100">{project.name}</h3> : null}
                    <p className="mt-1 text-sm text-zinc-400">{sourceName} Project · {project.external_project_id}</p>
                </div>
                <span className="inline-flex w-fit rounded-md border border-sky-500/25 bg-sky-500/10 px-2 py-1 text-xs font-semibold text-sky-200">
                    {sourceName}
                </span>
            </div>

            {freshnessMessage ? (
                <div role="status" className="mt-4 flex items-start gap-2 rounded-md border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-sm text-amber-200">
                    <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                    <span>{freshnessMessage}</span>
                </div>
            ) : null}

            {metadataRows.length > 0 ? (
                <dl className="mt-5 grid grid-cols-1 gap-x-6 gap-y-4 text-sm sm:grid-cols-2 lg:grid-cols-3">
                    {metadataRows.map((row) => (
                        <div key={row.label} className="min-w-0">
                            <dt className="text-xs font-semibold uppercase tracking-wide text-zinc-500">{row.label}</dt>
                            <dd className="mt-1 break-words text-zinc-200">{row.value}</dd>
                        </div>
                    ))}
                </dl>
            ) : null}

            <div className="mt-5 flex flex-col gap-2 border-t border-zinc-800 pt-4 text-xs text-zinc-500 sm:flex-row sm:items-center sm:justify-between">
                <p>
                    {project.source_freshness === 'fresh'
                        ? `Verified from ${sourceName} project data`
                        : `Source: ${sourceName}`}
                    {project.last_successful_enrichment_at
                        ? ` · Last checked ${formatProjectDate(project.last_successful_enrichment_at)}`
                        : ''}
                </p>
                {project.source_url ? (
                    <a
                        href={project.source_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        aria-label={`Open official ${sourceName} project source (opens in new tab)`}
                        className="inline-flex w-fit items-center gap-1.5 font-semibold text-sky-200 hover:text-sky-100"
                    >
                        Official Project Source
                        <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                    </a>
                ) : null}
            </div>

            {currentRoles.length > 0 ? (
                <div className="mt-5 border-t border-zinc-800 pt-5" aria-labelledby="project-leadership-heading">
                    <div className="flex items-center gap-2">
                        <UsersRound className="h-4 w-4 text-cyan-300" aria-hidden="true" />
                        <h3 id="project-leadership-heading" className="text-sm font-semibold uppercase tracking-wide text-zinc-200">Project Leadership</h3>
                    </div>
                    <p className="mt-2 text-xs leading-5 text-zinc-500">
                        Project leadership is project-level context and may differ from the tender&apos;s procurement contact.
                    </p>
                    <div className="mt-3 grid grid-cols-1 gap-2 md:grid-cols-2">
                        {currentRoles.map((role) => (
                            <RoleRow key={`${role.source_system}-${role.native_role}-${role.display_name}-${role.first_observed_at}`} role={role} />
                        ))}
                    </div>
                </div>
            ) : null}

            {historicalRoles.length > 0 ? (
                <details className="mt-4 border-t border-zinc-800 pt-4">
                    <summary className="flex cursor-pointer list-none items-center gap-2 text-sm font-medium text-zinc-300 marker:hidden hover:text-zinc-100">
                        <History className="h-4 w-4 text-zinc-500" aria-hidden="true" />
                        Previous project leadership ({historicalRoles.length})
                    </summary>
                    <div className="mt-3 grid grid-cols-1 gap-2 md:grid-cols-2">
                        {historicalRoles.map((role) => (
                            <RoleRow key={`${role.source_system}-${role.native_role}-${role.display_name}-${role.first_observed_at}`} role={role} historical />
                        ))}
                    </div>
                </details>
            ) : null}
        </section>
    );
}
