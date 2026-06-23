#!/usr/bin/env python3
"""Tests for the manifest generation script."""

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from generate_manifests import generate_manifests

SAMPLE_AGENTS = [
    {
        "name": "langgraph-react-agent",
        "displayName": "LangGraph ReAct Agent",
        "description": "General-purpose ReAct agent built with LangGraph.",
        "framework": "langgraph",
        "path": "agents/langgraph/templates/react_agent",
    },
    {
        "name": "crewai-websearch-agent",
        "displayName": "CrewAI WebSearch Agent",
        "description": "Web search agent built with CrewAI.",
        "framework": "crewai",
        "path": "agents/crewai/templates/websearch_agent",
    },
]

SAMPLE_URLS = {
    "langgraph-react-agent": "https://red.ht/abc123",
    "crewai-websearch-agent": "https://red.ht/def456",
}


def test_generates_odhdocument_per_agent(tmp_path):
    files = generate_manifests(SAMPLE_AGENTS, str(tmp_path), "3.6", SAMPLE_URLS)
    assert "agentic-starter-kits-langgraph-react-agent-tutorial.yaml" in files
    assert "agentic-starter-kits-crewai-websearch-agent-tutorial.yaml" in files


def test_generates_app_manifest(tmp_path):
    files = generate_manifests(SAMPLE_AGENTS, str(tmp_path), "3.6", SAMPLE_URLS)
    assert "agentic-starter-kits-app.yaml" in files


def test_generates_kustomization(tmp_path):
    files = generate_manifests(SAMPLE_AGENTS, str(tmp_path), "3.6", SAMPLE_URLS)
    assert "kustomization.yaml" in files


def test_odhdocument_structure(tmp_path):
    generate_manifests(SAMPLE_AGENTS, str(tmp_path), "3.6", SAMPLE_URLS)
    doc_path = tmp_path / "agentic-starter-kits-langgraph-react-agent-tutorial.yaml"
    doc = yaml.safe_load(doc_path.read_text())
    assert doc["apiVersion"] == "dashboard.opendatahub.io/v1"
    assert doc["kind"] == "OdhDocument"
    assert (
        doc["metadata"]["name"] == "agentic-starter-kits-langgraph-react-agent-tutorial"
    )
    assert (
        doc["metadata"]["annotations"]["opendatahub.io/categories"]
        == "Agent Templates,Getting started"
    )
    assert doc["spec"]["type"] == "tutorial"
    assert doc["spec"]["displayName"] == "LangGraph ReAct Agent"
    assert doc["spec"]["url"] == "https://red.ht/abc123"
    assert doc["spec"]["appName"] == "agentic-starter-kits"


def test_odhapplication_structure(tmp_path):
    generate_manifests(SAMPLE_AGENTS, str(tmp_path), "3.6", SAMPLE_URLS)
    app_path = tmp_path / "agentic-starter-kits-app.yaml"
    app = yaml.safe_load(app_path.read_text())
    assert app["apiVersion"] == "dashboard.opendatahub.io/v1"
    assert app["kind"] == "OdhApplication"
    assert app["metadata"]["name"] == "agentic-starter-kits"
    assert app["spec"]["hidden"] is True
    assert app["spec"]["provider"] == "Red Hat"


def test_kustomization_lists_all_resources(tmp_path):
    generate_manifests(SAMPLE_AGENTS, str(tmp_path), "3.6", SAMPLE_URLS)
    kust_path = tmp_path / "kustomization.yaml"
    kust = yaml.safe_load(kust_path.read_text())
    assert kust["apiVersion"] == "kustomize.config.k8s.io/v1beta1"
    assert kust["kind"] == "Kustomization"
    resources = kust["resources"]
    assert "agentic-starter-kits-app.yaml" in resources
    assert "agentic-starter-kits-langgraph-react-agent-tutorial.yaml" in resources
    assert "agentic-starter-kits-crewai-websearch-agent-tutorial.yaml" in resources


def test_fallback_url_without_short_urls(tmp_path):
    generate_manifests(SAMPLE_AGENTS, str(tmp_path), "3.6")
    doc_path = tmp_path / "agentic-starter-kits-langgraph-react-agent-tutorial.yaml"
    doc = yaml.safe_load(doc_path.read_text())
    expected = "https://github.com/red-hat-data-services/agentic-starter-kits/tree/rhoai-3.6/agents/langgraph/templates/react_agent"
    assert doc["spec"]["url"] == expected


def test_kustomization_resources_sorted(tmp_path):
    generate_manifests(SAMPLE_AGENTS, str(tmp_path), "3.6", SAMPLE_URLS)
    kust = yaml.safe_load((tmp_path / "kustomization.yaml").read_text())
    resources = kust["resources"]
    app_entry = resources[0]
    assert app_entry == "agentic-starter-kits-app.yaml"
    tutorial_entries = resources[1:]
    assert tutorial_entries == sorted(tutorial_entries)
