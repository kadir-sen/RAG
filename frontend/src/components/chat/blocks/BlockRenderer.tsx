import type { ChatBlock } from '../../../types/api';
import type { ViewerDoc } from '../../../stores/uiStore';
import MarkdownBlock from './MarkdownBlock';
import TableBlock from './TableBlock';
import ChartBlock from './ChartBlock';
import HtmlReportBlock from './HtmlReportBlock';
import ArtifactBlock from './ArtifactBlock';
import CaveatsBlock from './CaveatsBlock';
import ValidationBadgeBlock from './ValidationBadgeBlock';
import ClarificationBlock from './ClarificationBlock';

interface Props {
  blocks: ChatBlock[];
  onDocClick?: (doc: ViewerDoc) => void;
  onSend?: (text: string) => void;
}

/** Renders a chat-native block list. Unknown block types are skipped silently
 * so older frontends never break on newer backends. */
export default function BlockRenderer({ blocks, onSend }: Props) {
  return (
    <div className="flex flex-col gap-1">
      {blocks.map((b) => {
        switch (b.type) {
          case 'markdown_text':
            return <MarkdownBlock key={b.block_id} block={b} />;
          case 'data_table':
            return <TableBlock key={b.block_id} block={b} />;
          case 'chart':
            return <ChartBlock key={b.block_id} block={b} />;
          case 'html_report_section':
            return <HtmlReportBlock key={b.block_id} block={b} />;
          case 'artifact_link':
            return <ArtifactBlock key={b.block_id} block={b} />;
          case 'caveats':
            return <CaveatsBlock key={b.block_id} block={b} />;
          case 'validation_status':
            return <ValidationBadgeBlock key={b.block_id} block={b} />;
          case 'clarification':
            return (
              <ClarificationBlock key={b.block_id} block={b} onSend={onSend} />
            );
          default:
            return null;
        }
      })}
    </div>
  );
}
