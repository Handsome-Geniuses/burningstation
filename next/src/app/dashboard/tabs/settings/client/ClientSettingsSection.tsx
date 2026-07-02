"use client"

import React from "react"

import { Accordion } from "@/components/ui/accordion"

import { SectionCard } from "../_components/SectionCard"
import type { SchemaNode, SettingsObject, SettingsValue } from "../_components/types"

type ClientSettingsSectionProps = {
    draft: SettingsObject
    formId: string
    formRef: React.RefObject<HTMLFormElement | null>
    onChange: (path: string[], value: SettingsValue | "") => void
    onSave: (event: React.FormEvent<HTMLFormElement>) => void
    schema: SchemaNode
}

export const ClientSettingsSection = ({
    draft,
    formId,
    formRef,
    onChange,
    onSave,
    schema,
}: ClientSettingsSectionProps) => {
    return (
        <form id={formId} ref={formRef} onSubmit={onSave} className="flex flex-col gap-4">
            <Accordion type="multiple" className="flex flex-col gap-2 px-4">
                {Object.entries(schema.properties ?? {}).map(([sectionKey, sectionNode]) => (
                    <SectionCard
                        key={sectionKey}
                        sectionKey={sectionKey}
                        node={sectionNode}
                        value={draft[sectionKey]}
                        rootSchema={schema}
                        onChange={onChange}
                    />
                ))}
            </Accordion>
        </form>
    )
}
