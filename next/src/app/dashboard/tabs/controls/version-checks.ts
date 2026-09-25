import type { MeterState } from "../../store/system"
import type { SchemaNode, SettingsObject } from "../settings/_components/types"


export type VersionCheckStatus = "good" | "bad" | "missing" | "extra"

export type MeterVersionCheckRow = {
    key: string
    name: string
    version: number | null
    mod: number | null
    versionOperator: Operator | null
    modOperator: Operator | null
    settingVersion: number | null
    settingMod: number | null
    status: VersionCheckStatus
}

export type Operator = "eq" | "gt" | "gte" | "lt" | "lte"

type Constraint = {
    value: number
    operator: Operator | null
}

type ActualFirmware = {
    key: string
    name: string
    version: number | null
    mod: number | null
}

const OPERATORS = new Set<Operator>(["eq", "gt", "gte", "lt", "lte"])

function asRecord(value: unknown): Record<string, unknown> | null {
    return value && typeof value === "object" && !Array.isArray(value)
        ? value as Record<string, unknown>
        : null
}

function normalizeName(value: string) {
    return value.trim().toLowerCase()
}

function parseInteger(value: unknown): number | null {
    if (typeof value === "number") {
        return Number.isSafeInteger(value) && value >= 0 ? value : null
    }
    if (typeof value !== "string" || !/^\d+$/.test(value.trim())) return null

    const parsed = Number(value.trim())
    return Number.isSafeInteger(parsed) ? parsed : null
}

function firstValue(record: Record<string, unknown>, keys: string[]) {
    for (const key of keys) {
        if (key in record) return record[key]
    }
    return undefined
}

function parseConstraint(value: unknown): Constraint {
    const record = asRecord(value)
    const operator = record?.operator
    return {
        value: parseInteger(record?.value) ?? 0,
        operator: typeof operator === "string" && OPERATORS.has(operator as Operator)
            ? operator as Operator
            : null,
    }
}

function matches(actual: number, constraint: Constraint) {
    switch (constraint.operator) {
        case "eq": return actual === constraint.value
        case "gt": return actual > constraint.value
        case "gte": return actual >= constraint.value
        case "lt": return actual < constraint.value
        case "lte": return actual <= constraint.value
        default: return true
    }
}

function resolveSchemaNode(node: SchemaNode | undefined, root: SchemaNode) {
    if (!node?.$ref) return node
    const match = node.$ref.match(/^#\/\$defs\/(.+)$/)
    return match ? root.$defs?.[match[1]] ?? node : node
}

function buildInventory(meter: MeterState) {
    const inventory = new Map<string, ActualFirmware>()

    for (const [name, rawInfo] of Object.entries(meter.module_info ?? {})) {
        const info = asRecord(rawInfo) ?? {}
        inventory.set(normalizeName(name), {
            key: name,
            name,
            version: parseInteger(firstValue(info, ["ver", "fw"])),
            mod: parseInteger(firstValue(info, ["mod", "mod_func"])),
        })
    }

    for (const [name, version] of Object.entries(meter.firmwares ?? {})) {
        const normalized = normalizeName(name)
        if (inventory.has(normalized)) continue
        inventory.set(normalized, {
            key: name,
            name,
            version: parseInteger(version),
            mod: null,
        })
    }

    for (const [name, version] of Object.entries(meter.system_versions ?? {})) {
        const normalized = normalizeName(name)
        if (inventory.has(normalized)) continue
        inventory.set(normalized, {
            key: name,
            name,
            version: parseInteger(version),
            mod: null,
        })
    }

    return inventory
}

export function evaluateVersionChecks(
    meter: MeterState,
    settings: SettingsObject,
    schema: SchemaNode,
): MeterVersionCheckRow[] {
    const checks = asRecord(settings.version_checks)
    const checksSchema = resolveSchemaNode(schema.properties?.version_checks, schema)
    if (!checks || !checksSchema?.properties) return []

    const inventory = buildInventory(meter)
    const matchedActualNames = new Set<string>()
    const rows: MeterVersionCheckRow[] = []

    for (const [key, rawFieldSchema] of Object.entries(checksSchema.properties)) {
        const requirement = asRecord(checks[key])
        if (!requirement) continue

        const version = parseConstraint(requirement.version)
        const mod = parseConstraint(requirement.mod)
        if (!version.operator && !mod.operator) continue

        const fieldSchema = {
            ...(resolveSchemaNode(rawFieldSchema, schema) ?? {}),
            ...rawFieldSchema,
        }
        const candidateNames = [key, ...(fieldSchema.module_aliases ?? [])].map(normalizeName)
        const actualName = candidateNames.find((name) => inventory.has(name))
        const actual = actualName ? inventory.get(actualName) : undefined
        if (actualName) matchedActualNames.add(actualName)

        const requiredValues: Array<[number | null | undefined, Constraint]> = []
        if (version.operator) requiredValues.push([actual?.version, version])
        if (mod.operator) requiredValues.push([actual?.mod, mod])

        let status: VersionCheckStatus
        if (!actual || requiredValues.some(([value]) => value == null)) {
            status = "missing"
        } else if (requiredValues.every(([value, constraint]) => matches(value!, constraint))) {
            status = "good"
        } else {
            status = "bad"
        }

        rows.push({
            key,
            name: actual?.name ?? key,
            version: actual?.version ?? null,
            mod: actual?.mod ?? null,
            versionOperator: version.operator,
            modOperator: mod.operator,
            settingVersion: version.operator ? version.value : null,
            settingMod: mod.operator ? mod.value : null,
            status,
        })
    }

    const extras = [...inventory.entries()]
        .filter(([name]) => !matchedActualNames.has(name))
        .map(([, actual]) => ({
            ...actual,
            versionOperator: null,
            modOperator: null,
            settingVersion: null,
            settingMod: null,
            status: "extra" as const,
        }))
        .sort((left, right) => left.name.localeCompare(right.name))

    return [...rows, ...extras]
}
