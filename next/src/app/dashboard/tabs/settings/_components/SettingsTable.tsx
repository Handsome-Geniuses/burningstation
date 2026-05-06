"use client"

import React from "react"
import {
    BooleanRow,
    IntegerRow,
    ObjectRow,
    registerSettingsTable,
    resolveSchemaNode,
    TABLE_HEADER,
    UnsupportedRow,
} from "./shared"
import type { SettingsTableProps } from "./types"

export const SettingsTable = ({
    entries,
    currentValue,
    path,
    rootSchema,
    disabled,
    nested = false,
    onChange,
}: SettingsTableProps) => {
    return (
        <div className={`overflow-hidden border border-border ${nested ? "bg-background/70" : "rounded-lg bg-card"}`}>
            {!nested && (
                <div className={TABLE_HEADER}>
                    <div>Name</div>
                    <div>Description</div>
                    <div>Default</div>
                    <div>Control</div>
                </div>
            )}

            <div>
                {entries.map(([fieldKey, rawNode]) => {
                    const node = resolveSchemaNode(rawNode, rootSchema)
                    const value = currentValue?.[fieldKey]
                    const nextPath = [...path, fieldKey]

                    if (node.type === "object" || node.properties) {
                        return (
                            <ObjectRow
                                key={nextPath.join(".")}
                                fieldKey={fieldKey}
                                node={node}
                                value={value}
                                path={nextPath}
                                rootSchema={rootSchema}
                                disabled={disabled}
                                onChange={onChange}
                            />
                        )
                    }

                    if (node.type === "integer") {
                        return (
                            <IntegerRow
                                key={nextPath.join(".")}
                                fieldKey={fieldKey}
                                node={node}
                                value={value}
                                path={nextPath}
                                disabled={disabled}
                                onChange={onChange}
                            />
                        )
                    }

                    if (node.type === "boolean") {
                        return (
                            <BooleanRow
                                key={nextPath.join(".")}
                                fieldKey={fieldKey}
                                node={node}
                                value={value}
                                path={nextPath}
                                disabled={disabled}
                                onChange={onChange}
                            />
                        )
                    }

                    return <UnsupportedRow key={nextPath.join(".")} fieldKey={fieldKey} node={node} />
                })}
            </div>
        </div>
    )
}

registerSettingsTable(SettingsTable)
