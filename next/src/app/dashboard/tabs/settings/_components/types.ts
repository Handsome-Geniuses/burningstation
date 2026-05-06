export type SettingsValue = string | number | boolean | null | SettingsObject | SettingsValue[]
export type SettingsObject = { [key: string]: SettingsValue }

export type SchemaNode = {
    $ref?: string
    $defs?: Record<string, SchemaNode>
    type?: string
    title?: string
    description?: string
    minimum?: number
    maximum?: number
    default?: unknown
    properties?: Record<string, SchemaNode>
    items?: SchemaNode
}

export type SettingsPayload = {
    values: SettingsObject
    schema: SchemaNode
}

export type RowRendererProps = {
    fieldKey: string
    node: SchemaNode
    value: SettingsValue | undefined
    path: string[]
    disabled?: boolean
    onChange: (path: string[], value: SettingsValue | "") => void
}

export type ObjectRowProps = RowRendererProps & {
    rootSchema: SchemaNode
}

export type SettingsTableProps = {
    entries: Array<[string, SchemaNode]>
    currentValue: SettingsObject | null
    path: string[]
    rootSchema: SchemaNode
    disabled?: boolean
    nested?: boolean
    onChange: (path: string[], value: SettingsValue | "") => void
}
