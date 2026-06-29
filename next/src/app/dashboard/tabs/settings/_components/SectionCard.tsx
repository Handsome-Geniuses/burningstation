"use client"

import React from "react"
import {
    AccordionContent,
    AccordionItem,
    AccordionTrigger,
} from "@/components/ui/accordion"
import { formatLabel, resolveSchemaNode } from "./shared"
import { SettingsTable } from "./SettingsTable"
import type { SchemaNode, SettingsValue, SettingsObject } from "./types"

type SectionCardProps = {
    sectionKey: string
    node: SchemaNode
    value: SettingsValue | undefined
    rootSchema: SchemaNode
    disabled?: boolean
    onChange: (path: string[], value: SettingsValue | "") => void
}

export const SectionCard = ({
    sectionKey,
    node,
    value,
    rootSchema,
    disabled,
    onChange,
}: SectionCardProps) => {
    const resolved = resolveSchemaNode(node, rootSchema)
    const sectionValue =
        value && typeof value === "object" && !Array.isArray(value)
            ? (value as SettingsObject)
            : null

    return (
        <AccordionItem
            value={sectionKey}
            className="overflow-hidden rounded-xl border border-border bg-card shadow-md"
        >
            <AccordionTrigger className="px-4 py-4 hover:no-underline">
                <div className="text-left">
                    <div className="text-lg font-semibold leading-none tracking-none">{resolved.title ?? formatLabel(sectionKey)}</div>
                    <div className="pt-1 text-sm text-muted-foreground leading-none tracking-none">
                        {node.description ?? `Configure ${formatLabel(sectionKey).toLowerCase()} settings.`}
                    </div>
                </div>
            </AccordionTrigger>
            <AccordionContent className="p-0">
                <div className="p-1 pt-0">
                    <SettingsTable
                        entries={Object.entries(resolved.properties ?? {})}
                        currentValue={sectionValue}
                        path={[sectionKey]}
                        rootSchema={rootSchema}
                        disabled={disabled}
                        onChange={onChange}
                    />
                </div>
            </AccordionContent>
        </AccordionItem>
    )
}
